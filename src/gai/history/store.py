"""Global + local JSONL log locations and legacy merge helpers.

- Local: ``<git-root>/.gai/{usage,commands}.jsonl`` (current repo only)
- Global: ``~/.gai/{usage,commands}.jsonl`` (all repos; used by --report/--serve)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from gai.config import CONFIG_DIR
from gai.llm.history import project_root

_USAGE_NAME = "usage.jsonl"
_COMMANDS_NAME = "commands.jsonl"


def local_gai_dir(cwd: Path | None = None) -> Path:
    return project_root(cwd) / ".gai"


def global_gai_dir() -> Path:
    return CONFIG_DIR


def local_usage_log_path(cwd: Path | None = None) -> Path:
    override = os.environ.get("GAI_USAGE_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return local_gai_dir(cwd) / _USAGE_NAME


def global_usage_log_path() -> Path:
    override = os.environ.get("GAI_USAGE_LOG_GLOBAL", "").strip()
    if override:
        return Path(override).expanduser()
    return global_gai_dir() / _USAGE_NAME


def local_command_log_path(cwd: Path | None = None) -> Path:
    override = os.environ.get("GAI_HISTORY_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return local_gai_dir(cwd) / _COMMANDS_NAME


def global_command_log_path() -> Path:
    override = os.environ.get("GAI_HISTORY_LOG_GLOBAL", "").strip()
    if override:
        return Path(override).expanduser()
    return global_gai_dir() / _COMMANDS_NAME


def local_usage_report_path(cwd: Path | None = None) -> Path:
    return local_gai_dir(cwd) / "usage-report.html"


def global_usage_report_path() -> Path:
    return global_gai_dir() / "usage-report.html"


def local_history_report_path(cwd: Path | None = None) -> Path:
    return local_gai_dir(cwd) / "history-report.html"


def global_history_report_path() -> Path:
    return global_gai_dir() / "history-report.html"


def _line_fingerprint(data: dict) -> str:
    """Stable-ish key for idempotent merge (ignore missing optional fields)."""
    keys = (
        "ts",
        "repo_name",
        "action",
        "command",
        "subcommand",
        "model",
        "exit_code",
        "ok",
        "total_tokens",
        "duration_ms",
        "git_email",
        "argv",
    )
    payload = {k: data.get(k) for k in keys if k in data}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_jsonl_dicts(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    out.append(data)
    except OSError:
        return []
    return out


def _write_jsonl_dicts(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def merge_jsonl_into(
    target: Path,
    sources: list[tuple[Path, str]],
) -> int:
    """Merge source JSONL files into ``target``; fill empty repo_name from default.

    Returns number of newly appended rows.
    """
    existing = _read_jsonl_dicts(target)
    seen = {_line_fingerprint(d) for d in existing}
    added = 0
    for src, default_repo in sources:
        if not src.is_file():
            continue
        for data in _read_jsonl_dicts(src):
            row = dict(data)
            if not str(row.get("repo_name") or "").strip() and default_repo:
                row["repo_name"] = default_repo
            fp = _line_fingerprint(row)
            if fp in seen:
                continue
            existing.append(row)
            seen.add(fp)
            added += 1
    if added:
        # Keep chronological order when timestamps are comparable.
        existing.sort(key=lambda d: str(d.get("ts") or ""))
        _write_jsonl_dicts(target, existing)
    return added


def discover_sibling_project_logs(
    *,
    cwd: Path | None = None,
    names: tuple[str, ...] = ("CodeReviewAgent", "NatureLanguageCRUD"),
) -> list[tuple[Path, Path, str]]:
    """Return ``(usage_jsonl, commands_jsonl, repo_name)`` for known sibling repos."""
    root = project_root(cwd)
    parent = root.parent
    found: list[tuple[Path, Path, str]] = []
    seen_roots: set[Path] = set()

    candidates = [root]
    for name in names:
        candidates.append(parent / name)

    for repo in candidates:
        try:
            resolved = repo.resolve()
        except OSError:
            continue
        if resolved in seen_roots:
            continue
        gai = resolved / ".gai"
        usage = gai / _USAGE_NAME
        commands = gai / _COMMANDS_NAME
        if usage.is_file() or commands.is_file():
            seen_roots.add(resolved)
            found.append((usage, commands, resolved.name))
    return found


def _backfill_repo_name(row: dict) -> dict:
    """Fill empty repo_name from cwd path when possible."""
    if str(row.get("repo_name") or "").strip():
        return row
    cwd = str(row.get("cwd") or "")
    for name in ("CodeReviewAgent", "NatureLanguageCRUD"):
        if name in cwd.replace("\\", "/"):
            out = dict(row)
            out["repo_name"] = name
            return out
    # Fall back to last path segment of cwd.
    if cwd:
        try:
            name = Path(cwd).resolve().name
        except OSError:
            name = Path(cwd).name
        if name and not name.startswith("test_"):
            out = dict(row)
            out["repo_name"] = name
            return out
    return row


def _is_ephemeral_test_row(row: dict) -> bool:
    repo = str(row.get("repo_name") or "")
    cwd = str(row.get("cwd") or "").replace("\\", "/")
    model = str(row.get("model") or "")
    if repo.startswith("test_"):
        return True
    if model in {"gpt-test", "test-model"}:
        return True
    if "/pytest-" in cwd or "/pytest_of_" in cwd or "pytest-of-" in cwd:
        return True
    # Commands run from the user home directory (not a real project repo).
    try:
        home = Path.home().resolve()
        if cwd and Path(cwd).resolve() == home:
            return True
    except OSError:
        pass
    return False


def _ts_repo_index(sources: list[tuple[Path, str]]) -> dict[str, str]:
    """Map record timestamps → default repo when local source has that ts."""
    index: dict[str, str] = {}
    for src, name in sources:
        for row in _read_jsonl_dicts(src):
            ts = str(row.get("ts") or "")
            if ts and name:
                index.setdefault(ts, name)
    return index


def cleanup_global_logs(
    *,
    usage_sources: list[tuple[Path, str]] | None = None,
    command_sources: list[tuple[Path, str]] | None = None,
) -> dict[str, int]:
    """Backfill repo_name and drop obvious pytest pollution from global logs."""
    stats = {
        "usage_rewritten": 0,
        "commands_rewritten": 0,
        "usage_dropped": 0,
        "commands_dropped": 0,
    }
    usage_idx = _ts_repo_index(usage_sources or [])
    cmd_idx = _ts_repo_index(command_sources or [])
    for kind, path, idx in (
        ("usage", global_usage_log_path(), usage_idx),
        ("commands", global_command_log_path(), cmd_idx),
    ):
        rows = _read_jsonl_dicts(path)
        if not rows:
            continue
        cleaned: list[dict] = []
        dropped = 0
        changed = 0
        seen: set[str] = set()
        for row in rows:
            if _is_ephemeral_test_row(row):
                dropped += 1
                continue
            fixed = _backfill_repo_name(row)
            if not str(fixed.get("repo_name") or "").strip():
                guess = idx.get(str(fixed.get("ts") or ""))
                if guess:
                    fixed = dict(fixed)
                    fixed["repo_name"] = guess
                else:
                    # Orphan rows with no project attribution (old/test leftovers).
                    dropped += 1
                    continue
            if fixed.get("repo_name") != row.get("repo_name"):
                changed += 1
            fp = _line_fingerprint(fixed)
            if fp in seen:
                dropped += 1
                continue
            seen.add(fp)
            cleaned.append(fixed)
        if dropped or changed or len(cleaned) != len(rows):
            _write_jsonl_dicts(path, cleaned)
        stats[f"{kind}_dropped"] = dropped
        stats[f"{kind}_rewritten"] = changed
    return stats


def ensure_global_logs_merged(*, cwd: Path | None = None) -> dict[str, int]:
    """Idempotently merge discovered local project logs into ``~/.gai``.

    Safe to call on every --report/--serve; only appends missing fingerprints.
    """
    discovered = discover_sibling_project_logs(cwd=cwd)
    usage_sources = [(u, name) for u, _c, name in discovered]
    cmd_sources = [(c, name) for _u, c, name in discovered]
    added = {
        "usage": merge_jsonl_into(global_usage_log_path(), usage_sources),
        "commands": merge_jsonl_into(global_command_log_path(), cmd_sources),
    }
    cleanup_global_logs(usage_sources=usage_sources, command_sources=cmd_sources)
    return added
