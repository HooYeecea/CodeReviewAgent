"""Review policies scoped to one invocation, including resumed flows."""
from contextlib import contextmanager
from contextvars import ContextVar

_OPTIONS = ContextVar("review_options", default=None)
LEVELS = {"none": 0, "info": 1, "warning": 2, "critical": 3}


@contextmanager
def options(**values):
    merged = dict(_OPTIONS.get() or {})
    merged.update({k: v for k, v in values.items() if v is not None})
    token = _OPTIONS.set(merged)
    try:
        yield
    finally:
        _OPTIONS.reset(token)


def overrides():
    return dict(_OPTIONS.get() or {})


def bind_session(session):
    current = _OPTIONS.get()
    stored = session.data.get("review_options", {})
    if not isinstance(stored, dict) or set(stored) - {"fail_on", "require_complete"}:
        raise RuntimeError("Invalid saved review policy")
    if not isinstance(stored.get("fail_on", "none"), str) or stored.get("fail_on", "none") not in LEVELS:
        raise RuntimeError("Invalid saved severity threshold")
    if "require_complete" in stored and type(stored["require_complete"]) is not bool:
        raise RuntimeError("Invalid saved completeness policy")
    combined = {**stored, **(current or {})}
    if current is not None:
        current.update(combined)
    if combined:
        session.data["review_options"] = combined


def enforce(result):
    from gai.common.config import load_settings
    settings = load_settings()
    if not result.parsed_ok:
        raise RuntimeError("审查解析失败，已停止 / Review parsing failed")
    if settings.require_complete and (result.truncated_diff or result.coverage.get("state") in {"incomplete", "failed"}):
        raise RuntimeError("审查范围不完整，已停止；过长文本可分批审查，二进制内容需要人工检查。 / "
                           "Incomplete review; use smaller batches or --chunked for long text; inspect binary files manually.")
    threshold = LEVELS[settings.fail_on]
    if threshold and any(LEVELS[item.severity] >= threshold for item in result.review):
        raise RuntimeError(f"审查问题达到阻断级别，已停止 / Review blocked: {settings.fail_on}")
