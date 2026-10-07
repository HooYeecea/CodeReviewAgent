"""Persistent local LLM usage history (JSONL under ~/.gai)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from gai.config import CONFIG_DIR

DEFAULT_USAGE_LOG = CONFIG_DIR / "usage.jsonl"
# Soft cap: ~2–3 MB of short JSON lines; rotate by keeping a tail.
_MAX_BYTES = 3_000_000
_KEEP_TAIL_LINES = 12_000


@dataclass(frozen=True)
class UsageRecord:
    """One successful LLM call attributed to a gai action."""

    ts: str
    git_user: str
    git_email: str
    provider: str
    provider_name: str
    model: str
    action: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageRecord:
        return cls(
            ts=str(data.get("ts") or ""),
            git_user=str(data.get("git_user") or ""),
            git_email=str(data.get("git_email") or ""),
            provider=str(data.get("provider") or "unknown"),
            provider_name=str(data.get("provider_name") or ""),
            model=str(data.get("model") or ""),
            action=str(data.get("action") or ""),
            prompt_tokens=_as_optional_int(data.get("prompt_tokens")),
            completion_tokens=_as_optional_int(data.get("completion_tokens")),
            total_tokens=_as_optional_int(data.get("total_tokens")),
            base_url=str(data.get("base_url") or ""),
        )


def usage_log_path() -> Path:
    override = os.environ.get("GAI_USAGE_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_USAGE_LOG


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_usage_record(record: UsageRecord, *, path: Path | None = None) -> None:
    """Append one JSON line. Failures are swallowed so logging never breaks CLI."""
    target = path or usage_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        _maybe_rotate(target)
    except OSError:
        return


def load_usage_records(
    *,
    path: Path | None = None,
    limit: int | None = None,
    since: datetime | None = None,
    action: str | None = None,
    provider: str | None = None,
    git_user: str | None = None,
) -> list[UsageRecord]:
    """Load records oldest→newest. ``limit`` keeps the newest N after filters."""
    target = path or usage_log_path()
    if not target.is_file():
        return []

    action_key = (action or "").strip().lower()
    provider_key = (provider or "").strip().lower()
    user_key = (git_user or "").strip().lower()

    items: list[UsageRecord] = []
    try:
        with target.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                rec = UsageRecord.from_dict(data)
                if since is not None and not _ts_on_or_after(rec.ts, since):
                    continue
                if action_key and rec.action.lower() != action_key:
                    continue
                if provider_key and rec.provider.lower() != provider_key:
                    continue
                if user_key:
                    blob = f"{rec.git_user} {rec.git_email}".lower()
                    if user_key not in blob:
                        continue
                items.append(rec)
    except OSError:
        return []

    if limit is not None and limit >= 0:
        items = items[-limit:]
    return items


@dataclass
class UsageSummary:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_known: int = 0
    completion_known: int = 0
    total_known: int = 0


def summarize_records(records: Iterable[UsageRecord]) -> UsageSummary:
    summary = UsageSummary()
    for rec in records:
        summary.calls += 1
        if rec.prompt_tokens is not None:
            summary.prompt_tokens += rec.prompt_tokens
            summary.prompt_known += 1
        if rec.completion_tokens is not None:
            summary.completion_tokens += rec.completion_tokens
            summary.completion_known += 1
        if rec.total_tokens is not None:
            summary.total_tokens += rec.total_tokens
            summary.total_known += 1
    return summary


def group_by(
    records: Iterable[UsageRecord],
    key: str,
) -> list[tuple[str, UsageSummary]]:
    """Group summary by action | provider | model | user."""
    buckets: dict[str, UsageSummary] = {}
    order: list[str] = []
    for rec in records:
        if key == "action":
            label = rec.action or "(unknown)"
        elif key == "provider":
            label = rec.provider_name or rec.provider or "(unknown)"
        elif key == "model":
            label = rec.model or "(unknown)"
        elif key == "user":
            if rec.git_user and rec.git_email:
                label = f"{rec.git_user} <{rec.git_email}>"
            else:
                label = rec.git_user or rec.git_email or "(unknown)"
        else:
            label = "(unknown)"
        if label not in buckets:
            buckets[label] = UsageSummary()
            order.append(label)
        _accumulate(buckets[label], rec)
    return [(label, buckets[label]) for label in order]


def format_usage_table(
    records: list[UsageRecord],
    *,
    chinese: bool = False,
    group: str | None = None,
) -> str:
    """Human-readable history + optional group summary."""
    if not records:
        return "暂无本地用量记录。" if chinese else "No local usage records yet."

    lines: list[str] = []
    title = "本地用量记录" if chinese else "Local usage history"
    lines.append(title)
    lines.append("")

    for rec in records:
        who = _format_who(rec)
        provider = rec.provider_name or rec.provider or "?"
        tokens = _format_tokens(rec, chinese=chinese)
        action = rec.action or "?"
        when = rec.ts or "?"
        if chinese:
            lines.append(
                f"{when}  |  {who}  |  {provider} / {rec.model or '?'}  |  "
                f"{action}  |  {tokens}"
            )
        else:
            lines.append(
                f"{when}  |  {who}  |  {provider} / {rec.model or '?'}  |  "
                f"{action}  |  {tokens}"
            )

    summary = summarize_records(records)
    lines.append("")
    if chinese:
        lines.append(
            f"合计：{summary.calls} 次调用"
            + (
                f"，token {summary.total_tokens}"
                if summary.total_known == summary.calls and summary.calls
                else (
                    f"，已知合计 token {summary.total_tokens}"
                    f"（{summary.total_known}/{summary.calls} 条有 total）"
                    if summary.total_known
                    else "（部分调用未返回 token）"
                )
            )
        )
    else:
        lines.append(
            f"Total: {summary.calls} call(s)"
            + (
                f", {summary.total_tokens} tokens"
                if summary.total_known == summary.calls and summary.calls
                else (
                    f", known total tokens {summary.total_tokens}"
                    f" ({summary.total_known}/{summary.calls} with total)"
                    if summary.total_known
                    else " (some calls had no token usage)"
                )
            )
        )

    if group:
        lines.append("")
        header = {
            "action": ("按动作汇总", "By action"),
            "provider": ("按厂商汇总", "By provider"),
            "model": ("按模型汇总", "By model"),
            "user": ("按用户汇总", "By user"),
        }.get(group, ("汇总", "Summary"))
        lines.append(header[0] if chinese else header[1])
        for label, bucket in group_by(records, group):
            tok = (
                str(bucket.total_tokens)
                if bucket.total_known
                else ("未知" if chinese else "n/a")
            )
            if chinese:
                lines.append(f"  {label}: {bucket.calls} 次，token {tok}")
            else:
                lines.append(f"  {label}: {bucket.calls} call(s), tokens {tok}")

    path = usage_log_path()
    lines.append("")
    tip = f"日志文件：{path}" if chinese else f"Log file: {path}"
    lines.append(tip)
    return "\n".join(lines)


def _format_who(rec: UsageRecord) -> str:
    if rec.git_user and rec.git_email:
        return f"{rec.git_user} <{rec.git_email}>"
    return rec.git_user or rec.git_email or "(unknown)"


def _format_tokens(rec: UsageRecord, *, chinese: bool) -> str:
    if rec.total_tokens is not None:
        if chinese:
            parts = [f"合计 {rec.total_tokens}"]
            if rec.prompt_tokens is not None:
                parts.append(f"输入 {rec.prompt_tokens}")
            if rec.completion_tokens is not None:
                parts.append(f"输出 {rec.completion_tokens}")
            if len(parts) > 1:
                return f"{parts[0]}（{' + '.join(parts[1:])}）"
            return parts[0]
        parts = [f"total {rec.total_tokens}"]
        if rec.prompt_tokens is not None:
            parts.append(f"prompt {rec.prompt_tokens}")
        if rec.completion_tokens is not None:
            parts.append(f"completion {rec.completion_tokens}")
        if len(parts) > 1:
            return f"{parts[0]} ({' + '.join(parts[1:])})"
        return parts[0]
    if rec.prompt_tokens is not None or rec.completion_tokens is not None:
        bits = []
        if rec.prompt_tokens is not None:
            bits.append(
                f"输入 {rec.prompt_tokens}" if chinese else f"prompt {rec.prompt_tokens}"
            )
        if rec.completion_tokens is not None:
            bits.append(
                f"输出 {rec.completion_tokens}"
                if chinese
                else f"completion {rec.completion_tokens}"
            )
        return " + ".join(bits)
    return "无 token" if chinese else "no tokens"


def _accumulate(summary: UsageSummary, rec: UsageRecord) -> None:
    summary.calls += 1
    if rec.prompt_tokens is not None:
        summary.prompt_tokens += rec.prompt_tokens
        summary.prompt_known += 1
    if rec.completion_tokens is not None:
        summary.completion_tokens += rec.completion_tokens
        summary.completion_known += 1
    if rec.total_tokens is not None:
        summary.total_tokens += rec.total_tokens
        summary.total_known += 1


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ts_on_or_after(ts: str, since: datetime) -> bool:
    parsed = _parse_ts(ts)
    if parsed is None:
        return True
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= since


def _parse_ts(ts: str) -> datetime | None:
    text = (ts or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _maybe_rotate(path: Path) -> None:
    try:
        if not path.is_file() or path.stat().st_size <= _MAX_BYTES:
            return
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= _KEEP_TAIL_LINES:
            return
        kept = lines[-_KEEP_TAIL_LINES:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(kept), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return
