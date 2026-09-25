"""OpenAI-compatible Chat Completions client."""

from __future__ import annotations

from typing import Any

import httpx

from gai.config import Settings
from gai.llm.usage import record_llm_call


class LLMError(RuntimeError):
    """Raised when the LLM API call fails."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "api",
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.detail = detail


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


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
        record_llm_call(
            model=model_name or self.settings.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        return content


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
