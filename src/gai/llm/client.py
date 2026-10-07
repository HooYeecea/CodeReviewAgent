"""OpenAI-compatible Chat Completions client."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from gai.config import Settings
from gai.git_ops import current_git_identity
from gai.llm.history import UsageRecord, append_usage_record, now_iso
from gai.llm.usage import get_llm_action, get_llm_usage_meta, record_llm_call

_RETRYABLE_KINDS = frozenset({"timeout", "network", "rate_limit", "server"})
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF = (1.0, 2.0, 4.0)


class LLMError(RuntimeError):
    """Raised when the LLM API call fails."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "api",
        status_code: int | None = None,
        detail: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


def classify_http_error(status_code: int, body: str) -> str:
    """Map HTTP status + body hints to a stable LLMError.kind."""
    text = (body or "").lower()
    billing_hints = (
        "insufficient",
        "balance",
        "quota",
        "billing",
        "payment",
        "exceeded your current quota",
        "credit",
        "arrears",
        "欠费",
        "余额",
        "配额",
    )
    if status_code == 401:
        return "unauthorized"
    if status_code == 402:
        return "billing"
    if status_code == 429:
        return "rate_limit"
    if status_code == 403:
        if any(h in text for h in billing_hints):
            return "billing"
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code >= 500:
        return "server"
    if any(h in text for h in billing_hints):
        return "billing"
    return "api"


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, 30.0)


def _retry_delay(attempt: int, exc: LLMError) -> float:
    if exc.retry_after is not None:
        return exc.retry_after
    idx = min(max(attempt - 1, 0), len(_DEFAULT_BACKOFF) - 1)
    return _DEFAULT_BACKOFF[idx]


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self.max_attempts = max(1, int(max_attempts))
        self._sleep = sleep or time.sleep

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
    ) -> str:
        if not self.settings.api_key:
            raise LLMError(
                "API key not configured. Set GAI_API_KEY / OPENAI_API_KEY "
                "or run: gai config --api-key <key>",
                kind="missing_key",
            )

        started = time.perf_counter()
        last_error: LLMError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                content, usage = self._chat_once(
                    system=system,
                    user=user,
                    temperature=temperature,
                )
                model, prompt_tokens, completion_tokens, total_tokens = usage
                record_llm_call(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                self._persist_usage(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    ok=True,
                    duration_ms=_elapsed_ms(started),
                )
                return content
            except LLMError as exc:
                last_error = exc
                if exc.kind not in _RETRYABLE_KINDS or attempt >= self.max_attempts:
                    self._persist_usage(
                        model=self.settings.model,
                        prompt_tokens=None,
                        completion_tokens=None,
                        total_tokens=None,
                        ok=False,
                        duration_ms=_elapsed_ms(started),
                        error_kind=exc.kind,
                    )
                    raise
                self._sleep(_retry_delay(attempt, exc))

        assert last_error is not None
        self._persist_usage(
            model=self.settings.model,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            ok=False,
            duration_ms=_elapsed_ms(started),
            error_kind=last_error.kind,
        )
        raise last_error

    def _chat_once(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
    ) -> tuple[str, tuple[str, int | None, int | None, int | None]]:
        url = f"{self.settings.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"LLM request timed out after {self.settings.timeout}s",
                kind="timeout",
                detail=str(exc),
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"LLM request failed: {exc}",
                kind="network",
                detail=str(exc),
            ) from exc

        if response.status_code >= 400:
            detail = (response.text or "")[:500]
            kind = classify_http_error(response.status_code, detail)
            raise LLMError(
                f"LLM API error {response.status_code}: {detail}",
                kind=kind,
                status_code=response.status_code,
                detail=detail,
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(
                "Unexpected LLM response shape",
                kind="bad_response",
                detail=str(exc),
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned empty content", kind="empty")

        usage = data.get("usage") if isinstance(data, dict) else None
        prompt_tokens = completion_tokens = total_tokens = None
        if isinstance(usage, dict):
            prompt_tokens = _as_int(usage.get("prompt_tokens"))
            completion_tokens = _as_int(usage.get("completion_tokens"))
            total_tokens = _as_int(usage.get("total_tokens"))
        model_name = ""
        if isinstance(data, dict):
            model_name = str(data.get("model") or "").strip()
        resolved_model = model_name or self.settings.model
        return content, (resolved_model, prompt_tokens, completion_tokens, total_tokens)

    def _persist_usage(
        self,
        *,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        ok: bool,
        duration_ms: int | None,
        error_kind: str = "",
    ) -> None:
        # Lazy import: balance ↔ client already share types; avoid import cycle.
        from gai import __version__
        from gai.llm.balance import detect_provider

        provider = detect_provider(self.settings.base_url)
        git_user, git_email = current_git_identity()
        meta = get_llm_usage_meta()
        append_usage_record(
            UsageRecord(
                ts=now_iso(),
                git_user=git_user,
                git_email=git_email,
                provider=provider.id,
                provider_name=provider.name_en,
                model=model,
                action=get_llm_action() or "unknown",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                base_url=self.settings.base_url,
                action_detail=meta.action_detail,
                branch=meta.branch,
                files_count=meta.files_count,
                diff_chars=meta.diff_chars,
                truncated=meta.truncated,
                commit_count=meta.commit_count,
                since=meta.since,
                ok=ok,
                duration_ms=duration_ms,
                error_kind=error_kind,
                gai_version=__version__,
            )
        )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
