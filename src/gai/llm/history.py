"""Persistent LLM usage history (JSONL under project/.gai and ~/.gai)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Soft cap: ~2–3 MB of short JSON lines; rotate by keeping a tail.
_MAX_BYTES = 3_000_000
_KEEP_TAIL_LINES = 12_000
_USAGE_RELATIVE = Path(".gai") / "usage.jsonl"


@dataclass(frozen=True)
class UsageRecord:
    """One LLM call attributed to a gai action (success or final failure)."""

    ts: str
    git_user: str
    git_email: str
    repo_name: str = ""
    remote_name: str | None = None
    provider: str = ""
    provider_name: str = ""
    model: str = ""
    action: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    base_url: str = ""
    action_detail: str = ""
    branch: str = ""
    files_count: int | None = None
    diff_chars: int | None = None
    truncated: bool | None = None
    commit_count: int | None = None
    since: str = ""
    ok: bool | None = None
    duration_ms: int | None = None
    error_kind: str = ""
    gai_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Omit empty optional fields; always emit ``remote_name`` (may be JSON null)."""
        raw = asdict(self)
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "remote_name":
                out[key] = value  # keep explicit null when no remote
                continue
            if value is None:
                continue
            if value == "" and key not in {
                "ts",
                "git_user",
                "git_email",
                "repo_name",
                "provider",
                "provider_name",
                "model",
                "action",
            }:
                continue
            out[key] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageRecord:
        truncated = data.get("truncated")
        if truncated is not None:
            truncated = bool(truncated)
        ok = data.get("ok")
        if ok is not None:
            ok = bool(ok)
        remote_raw = data.get("remote_name", None)
        if remote_raw is None or remote_raw == "":
            remote_name = None
        else:
            remote_name = str(remote_raw)
        return cls(
            ts=str(data.get("ts") or ""),
            git_user=str(data.get("git_user") or ""),
            git_email=str(data.get("git_email") or ""),
            repo_name=str(data.get("repo_name") or ""),
            remote_name=remote_name,
            provider=str(data.get("provider") or "unknown"),
            provider_name=str(data.get("provider_name") or ""),
            model=str(data.get("model") or ""),
            action=str(data.get("action") or ""),
            prompt_tokens=_as_optional_int(data.get("prompt_tokens")),
            completion_tokens=_as_optional_int(data.get("completion_tokens")),
            total_tokens=_as_optional_int(data.get("total_tokens")),
            base_url=str(data.get("base_url") or ""),
            action_detail=str(data.get("action_detail") or ""),
            branch=str(data.get("branch") or ""),
            files_count=_as_optional_int(data.get("files_count")),
            diff_chars=_as_optional_int(data.get("diff_chars")),
            truncated=truncated,
            commit_count=_as_optional_int(data.get("commit_count")),
            since=str(data.get("since") or ""),
            ok=ok,
            duration_ms=_as_optional_int(data.get("duration_ms")),
            error_kind=str(data.get("error_kind") or ""),
            gai_version=str(data.get("gai_version") or ""),
        )


def project_root(cwd: Path | None = None) -> Path:
    """Git repo toplevel when available; otherwise current working directory."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    try:
        from gai.git_ops import run_git

        result = run_git("rev-parse", "--show-toplevel", cwd=base, trace=False)
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return base.resolve()


def usage_log_path(cwd: Path | None = None, *, scope: str = "local") -> Path:
    """Usage JSONL path.

    ``scope="local"`` → ``<project>/.gai/usage.jsonl`` (``GAI_USAGE_LOG`` override).
    ``scope="global"`` → ``~/.gai/usage.jsonl`` (``GAI_USAGE_LOG_GLOBAL`` override).
    """
    from gai.log_store import global_usage_log_path, local_usage_log_path

    if scope == "global":
        return global_usage_log_path()
    return local_usage_log_path(cwd)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _append_usage_to(target: Path, record: UsageRecord) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        _maybe_rotate(target)
    except OSError:
        return
    try:
        from gai.llm.usage_report import sync_usage_data_file

        sync_usage_data_file(log_path=target)
    except Exception:
        return


def append_usage_record(record: UsageRecord, *, path: Path | None = None) -> None:
    """Append one JSON line. Failures are swallowed so logging never breaks CLI.

    When ``path`` is omitted, dual-writes to local project ``.gai`` and global
    ``~/.gai`` (skipped if both resolve to the same file).
    """
    if path is not None:
        _append_usage_to(path, record)
        return

    from gai.log_store import global_usage_log_path, local_usage_log_path

    local = local_usage_log_path()
    _append_usage_to(local, record)
    # Explicit GAI_USAGE_LOG override (tests/custom) → single destination only.
    if os.environ.get("GAI_USAGE_LOG", "").strip():
        return
    try:
        global_path = global_usage_log_path()
        if global_path.resolve() != local.resolve():
            _append_usage_to(global_path, record)
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
        action = rec.action_detail or rec.action or "?"
        when = rec.ts or "?"
        extras = _format_extras(rec, chinese=chinese)
        status = ""
        if rec.ok is False:
            status = "  |  FAIL" if not chinese else "  |  失败"
            if rec.error_kind:
                status += f"({rec.error_kind})"
        line = (
            f"{when}  |  {who}  |  {provider} / {rec.model or '?'}  |  "
            f"{action}  |  {tokens}"
        )
        if extras:
            line += f"  |  {extras}"
        line += status
        lines.append(line)

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
        who = f"{rec.git_user} <{rec.git_email}>"
    else:
        who = rec.git_user or rec.git_email or "(unknown)"
    if not rec.repo_name and rec.remote_name is None:
        return who
    remote = rec.remote_name if rec.remote_name is not None else "null"
    if rec.repo_name:
        return f"{who} @ {rec.repo_name} / remote={remote}"
    return f"{who} @ remote={remote}"


def _format_extras(rec: UsageRecord, *, chinese: bool) -> str:
    bits: list[str] = []
    if rec.branch:
        bits.append(rec.branch)
    if rec.files_count is not None:
        bits.append(
            f"{rec.files_count} 文件" if chinese else f"{rec.files_count} files"
        )
    if rec.diff_chars is not None:
        bits.append(f"{rec.diff_chars} chars")
    if rec.commit_count is not None:
        bits.append(
            f"{rec.commit_count} 提交" if chinese else f"{rec.commit_count} commits"
        )
    if rec.since:
        bits.append(f"since={rec.since}")
    if rec.truncated:
        bits.append("truncated" if not chinese else "已截断")
    if rec.duration_ms is not None:
        bits.append(f"{rec.duration_ms}ms")
    return ", ".join(bits)


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
