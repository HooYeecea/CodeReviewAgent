"""Per-invocation LLM call usage tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallInfo:
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


_LLM_LOG: list[LLMCallInfo] = []


def clear_llm_usage() -> None:
    global _LLM_LOG
    _LLM_LOG = []


def record_llm_call(
    *,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    _LLM_LOG.append(
        LLMCallInfo(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def get_llm_calls() -> list[LLMCallInfo]:
    return list(_LLM_LOG)


def usage_totals(calls: list[LLMCallInfo] | None = None) -> tuple[int | None, int | None, int | None]:
    """Return (prompt, completion, total). None if no numeric usage reported."""
    items = calls if calls is not None else _LLM_LOG
    if not items:
        return None, None, None

    def _sum(attr: str) -> int | None:
        vals = [getattr(c, attr) for c in items if getattr(c, attr) is not None]
        if not vals:
            return None
        return int(sum(vals))

    prompt = _sum("prompt_tokens")
    completion = _sum("completion_tokens")
    total = _sum("total_tokens")
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return prompt, completion, total
