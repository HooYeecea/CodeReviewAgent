"""Git subprocess core: errors, tracing, run_git, ensure_repo."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

class GitError(RuntimeError):
    """Raised when a git command fails or the cwd is not a repo."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


_TRACE_ENABLED = False
_TRACE_LOG: list[str] = []


def set_tracing(enabled: bool) -> None:
    """Enable/disable git command tracing for the current invocation."""
    global _TRACE_ENABLED, _TRACE_LOG
    _TRACE_ENABLED = bool(enabled)
    _TRACE_LOG = []


def get_traced_commands() -> list[str]:
    return list(_TRACE_LOG)


def clear_trace() -> None:
    global _TRACE_LOG
    _TRACE_LOG = []


def _record_trace(*args: str) -> None:
    if not _TRACE_ENABLED:
        return
    try:
        joined = shlex.join(args)
    except Exception:
        joined = " ".join(args)
    _TRACE_LOG.append(f"git {joined}")


def run_git(
    *args: str,
    cwd: Path | None = None,
    trace: bool = True,
) -> GitResult:
    if trace:
        _record_trace(*args)
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH", code="no_git") from exc

    return GitResult(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        returncode=completed.returncode,
    )


def ensure_repo(cwd: Path | None = None) -> Path:
    result = run_git("rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or "not a git repository",
            code="not_repo",
        )
    return Path(result.stdout.strip())

