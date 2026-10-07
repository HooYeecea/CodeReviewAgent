"""gai command execution history (JSONL under project/.gai and ~/.gai)."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gai.llm.history import now_iso, project_root

# Soft cap similar to usage.jsonl.
_MAX_BYTES = 3_000_000
_KEEP_TAIL_LINES = 12_000
_HISTORY_RELATIVE = Path(".gai") / "commands.jsonl"

# Option names whose following token (or =value) must be redacted.
_SECRET_OPTS = {
    "--api-key",
    "--apikey",
    "--token",
    "--password",
    "--secret",
}

# Known options that take a value (used when peeling leading flags to find command).
_VALUE_OPTS = {
    "--api-key",
    "--base-url",
    "--model",
    "--shell",
    "--since",
    "--until",
    "--action",
    "--provider",
    "--user",
    "--group",
    "--limit",
    "--remote",
    "--author",
    "--message",
    "--path",
    "-n",
    "-s",
    "-a",
    "-u",
    "-g",
    "-m",
    "-r",
}


@dataclass(frozen=True)
class CommandRecord:
    """One gai CLI invocation (success or failure)."""

    ts: str
    command: str
    argv: list[str]
    exit_code: int
    ok: bool
    duration_ms: int | None = None
    subcommand: str = ""
    git_user: str = ""
    git_email: str = ""
    repo_name: str = ""
    remote_name: str | None = None
    cwd: str = ""
    gai_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "remote_name":
                out[key] = value
                continue
            if value is None:
                continue
            if value == "" and key not in {
                "ts",
                "command",
                "git_user",
                "git_email",
                "repo_name",
            }:
                continue
            if key == "argv" and not value:
                continue
            out[key] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandRecord:
        argv_raw = data.get("argv") or []
        if isinstance(argv_raw, str):
            argv = [argv_raw]
        elif isinstance(argv_raw, list):
            argv = [str(x) for x in argv_raw]
        else:
            argv = []
        remote_raw = data.get("remote_name", None)
        if remote_raw is None or remote_raw == "":
            remote_name = None
        else:
            remote_name = str(remote_raw)
        exit_code = data.get("exit_code", 0)
        try:
            exit_code_i = int(exit_code)
        except (TypeError, ValueError):
            exit_code_i = 1
        ok = data.get("ok")
        if ok is None:
            ok = exit_code_i == 0
        else:
            ok = bool(ok)
        duration = data.get("duration_ms")
        try:
            duration_ms = int(duration) if duration is not None and duration != "" else None
        except (TypeError, ValueError):
            duration_ms = None
        return cls(
            ts=str(data.get("ts") or ""),
            command=str(data.get("command") or ""),
            argv=argv,
            exit_code=exit_code_i,
            ok=ok,
            duration_ms=duration_ms,
            subcommand=str(data.get("subcommand") or ""),
            git_user=str(data.get("git_user") or ""),
            git_email=str(data.get("git_email") or ""),
            repo_name=str(data.get("repo_name") or ""),
            remote_name=remote_name,
            cwd=str(data.get("cwd") or ""),
            gai_version=str(data.get("gai_version") or ""),
        )


def history_enabled() -> bool:
    """Respect ``GAI_HISTORY``: ``0`` / ``false`` / ``off`` / ``no`` disables."""
    raw = os.environ.get("GAI_HISTORY", "").strip().lower()
    if raw in {"0", "false", "off", "no", "disable", "disabled"}:
        return False
    return True


def command_log_path(cwd: Path | None = None, *, scope: str = "local") -> Path:
    """Command JSONL path.

    ``scope="local"`` → ``<project>/.gai/commands.jsonl`` (``GAI_HISTORY_LOG``).
    ``scope="global"`` → ``~/.gai/commands.jsonl`` (``GAI_HISTORY_LOG_GLOBAL``).
    """
    from gai.log_store import global_command_log_path, local_command_log_path

    if scope == "global":
        return global_command_log_path()
    return local_command_log_path(cwd)


def sanitize_argv(argv: list[str]) -> list[str]:
    """Return argv with secret option values replaced by ``***``."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("--") and "=" in token:
            name, _, _value = token.partition("=")
            if name.lower() in _SECRET_OPTS or _looks_secret_value(_value):
                out.append(f"{name}=***")
            else:
                out.append(token)
            i += 1
            continue
        if token.lower() in _SECRET_OPTS:
            out.append(token)
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                out.append("***")
                i += 2
                continue
            i += 1
            continue
        if _looks_secret_value(token):
            out.append("***")
        else:
            out.append(token)
        i += 1
    return out


def extract_command(argv: list[str]) -> tuple[str, str]:
    """Return ``(command, subcommand)`` from argv (best-effort)."""
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("-"):
            if (
                "=" not in token
                and token in _VALUE_OPTS
                and i + 1 < len(argv)
                and not argv[i + 1].startswith("-")
            ):
                i += 2
                continue
            i += 1
            continue
        command = token
        sub = ""
        if command in {"completion"}:
            j = i + 1
            while j < len(argv):
                nxt = argv[j]
                if nxt.startswith("-"):
                    if (
                        "=" not in nxt
                        and nxt in _VALUE_OPTS
                        and j + 1 < len(argv)
                        and not argv[j + 1].startswith("-")
                    ):
                        j += 2
                        continue
                    j += 1
                    continue
                sub = nxt
                break
        return command, sub
    return "", ""


def _append_command_to(target: Path, record: CommandRecord) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        _maybe_rotate(target)
    except OSError:
        return
    try:
        from gai.history_report import sync_history_data_file

        sync_history_data_file(log_path=target)
    except Exception:
        return


def append_command_record(record: CommandRecord, *, path: Path | None = None) -> None:
    """Append one JSON line. Failures are swallowed so logging never breaks CLI.

    When ``path`` is omitted, dual-writes to local project ``.gai`` and global
    ``~/.gai``.
    """
    if path is not None:
        _append_command_to(path, record)
        return

    from gai.log_store import global_command_log_path, local_command_log_path

    local = local_command_log_path()
    _append_command_to(local, record)
    # Explicit GAI_HISTORY_LOG override (tests/custom) → single destination only.
    if os.environ.get("GAI_HISTORY_LOG", "").strip():
        return
    try:
        global_path = global_command_log_path()
        if global_path.resolve() != local.resolve():
            _append_command_to(global_path, record)
    except OSError:
        return


def load_command_records(
    *,
    path: Path | None = None,
    limit: int | None = None,
    since: datetime | None = None,
    command: str | None = None,
    ok: bool | None = None,
) -> list[CommandRecord]:
    """Load records oldest→newest. ``limit`` keeps the newest N after filters."""
    target = path or command_log_path()
    if not target.is_file():
        return []

    command_key = (command or "").strip().lower()
    items: list[CommandRecord] = []
    try:
        with target.open("r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                rec = CommandRecord.from_dict(data)
                if since is not None and not _ts_on_or_after(rec.ts, since):
                    continue
                if command_key:
                    blob = f"{rec.command} {rec.subcommand}".strip().lower()
                    if command_key not in blob and command_key != rec.command.lower():
                        continue
                if ok is not None and rec.ok is not ok:
                    continue
                items.append(rec)
    except OSError:
        return []

    if limit is not None and limit >= 0:
        items = items[-limit:]
    return items


def format_command_table(
    records: list[CommandRecord],
    *,
    chinese: bool = False,
) -> str:
    """Human-readable command history (newest first)."""
    if not records:
        return "暂无本地命令执行记录。" if chinese else "No local command history yet."

    lines: list[str] = []
    title = "本地命令执行记录" if chinese else "Local command history"
    lines.append(title)
    lines.append("")

    # Show newest first for a history view.
    for rec in reversed(records):
        when = rec.ts or "?"
        cmd = rec.command or "?"
        if rec.subcommand:
            cmd = f"{cmd} {rec.subcommand}"
        argv_s = " ".join(shlex.quote(a) for a in rec.argv) if rec.argv else cmd
        who = _format_who(rec)
        status = "OK" if rec.ok else f"FAIL({rec.exit_code})"
        if chinese and not rec.ok:
            status = f"失败({rec.exit_code})"
        elif chinese and rec.ok:
            status = "成功"
        dur = f"{rec.duration_ms}ms" if rec.duration_ms is not None else ""
        bits = [when, who, argv_s, status]
        if dur:
            bits.append(dur)
        lines.append("  |  ".join(bits))

    lines.append("")
    ok_n = sum(1 for r in records if r.ok)
    fail_n = len(records) - ok_n
    if chinese:
        lines.append(f"合计：{len(records)} 次（成功 {ok_n}，失败 {fail_n}）")
    else:
        lines.append(f"Total: {len(records)} run(s) ({ok_n} ok, {fail_n} failed)")

    path = command_log_path()
    tip = f"日志文件：{path}" if chinese else f"Log file: {path}"
    lines.append(tip)
    return "\n".join(lines)


def maybe_record_command(
    argv: list[str],
    *,
    exit_code: int,
    duration_ms: int | None = None,
    path: Path | None = None,
) -> None:
    """Best-effort append for a finished CLI run. Never raises."""
    try:
        if not history_enabled():
            return
        # Click/Typer completion probes must not pollute history.
        if os.environ.get("_GAI_COMPLETE") or os.environ.get("_TYPER_COMPLETE"):
            return
        from gai import __version__
        from gai.git_ops import current_git_identity, current_repo_identity

        safe = sanitize_argv(list(argv))
        command, subcommand = extract_command(safe)
        git_user, git_email = current_git_identity()
        repo_name, remote_name = current_repo_identity()
        append_command_record(
            CommandRecord(
                ts=now_iso(),
                command=command or "(root)",
                argv=safe,
                exit_code=int(exit_code),
                ok=int(exit_code) == 0,
                duration_ms=duration_ms,
                subcommand=subcommand,
                git_user=git_user,
                git_email=git_email,
                repo_name=repo_name,
                remote_name=remote_name,
                cwd=str(Path.cwd()),
                gai_version=__version__,
            ),
            path=path,
        )
    except Exception:
        return


def _looks_secret_value(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith("sk-") or lower.startswith("sk_"):
        return True
    if lower.startswith("ghp_") or lower.startswith("github_pat_"):
        return True
    return False


def _format_who(rec: CommandRecord) -> str:
    if rec.git_user and rec.git_email:
        who = f"{rec.git_user} <{rec.git_email}>"
    else:
        who = rec.git_user or rec.git_email or "(unknown)"
    if rec.repo_name:
        return f"{who} @ {rec.repo_name}"
    return who


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
