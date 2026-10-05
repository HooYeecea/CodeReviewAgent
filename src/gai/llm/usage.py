"""Per-invocation LLM call usage tracking (context-local, not a process global)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallInfo:
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


_LLM_LOG: ContextVar[list[LLMCallInfo]] = ContextVar("gai_llm_log")


def _log() -> list[LLMCallInfo]:
    try:
        return _LLM_LOG.get()
    except LookupError:
        items: list[LLMCallInfo] = []
        _LLM_LOG.set(items)
        return items


def clear_llm_usage() -> None:
    _LLM_LOG.set([])


def record_llm_call(
    *,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    _log().append(
        LLMCallInfo(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def get_llm_calls() -> list[LLMCallInfo]:
    return list(_log())


def usage_totals(
    calls: list[LLMCallInfo] | None = None,
) -> tuple[int | None, int | None, int | None]:
    """Return (prompt, completion, total).

    Totals are only reported when every call has that field.
    Missing ``total_tokens`` is left as None (never estimated).
    """
    items = calls if calls is not None else _log()
    if not items:
        return None, None, None

    def _sum_if_complete(attr: str) -> int | None:
        vals = [getattr(c, attr) for c in items]
        if any(v is None for v in vals):
            return None
        return int(sum(vals))

    return (
        _sum_if_complete("prompt_tokens"),
        _sum_if_complete("completion_tokens"),
        _sum_if_complete("total_tokens"),
    )
