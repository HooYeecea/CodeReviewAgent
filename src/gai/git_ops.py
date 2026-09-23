"""Thin wrappers around system git via subprocess."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command fails or the cwd is not a repo."""


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


def run_git(*args: str, cwd: Path | None = None) -> GitResult:
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
        raise GitError("git executable not found on PATH") from exc

    return GitResult(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        returncode=completed.returncode,
    )


def ensure_repo(cwd: Path | None = None) -> Path:
    result = run_git("rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "not a git repository")
    return Path(result.stdout.strip())


def has_staged_changes(cwd: Path | None = None) -> bool:
    ensure_repo(cwd)
    # --quiet: exit 0 if no diff, 1 if there is a diff, >1 on error
    result = run_git("diff", "--cached", "--quiet", cwd=cwd)
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    raise GitError(result.stderr.strip() or "failed to check staged changes")


def staged_name_status(cwd: Path | None = None) -> list[tuple[str, str]]:
    """Return list of (status, path) for staged files."""
    ensure_repo(cwd)
    result = run_git(
        "diff",
        "--cached",
        "--name-status",
        "-z",
        cwd=cwd,
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to list staged files")

    parts = [p for p in result.stdout.split("\0") if p]
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        # Rename/copy: status\0old\0new
        if status.startswith("R") or status.startswith("C"):
            if i + 2 >= len(parts):
                break
            entries.append((status, parts[i + 2]))
            i += 3
        else:
            if i + 1 >= len(parts):
                break
            entries.append((status, parts[i + 1]))
            i += 2
    return entries


def _should_ignore(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    name = Path(path).name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern):
            return True
    return False


_DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$", re.MULTILINE)


def filter_diff_by_ignore(diff_text: str, ignore_patterns: tuple[str, ...] | list[str]) -> str:
    """Drop whole file sections whose path matches ignore patterns."""
    if not diff_text.strip() or not ignore_patterns:
        return diff_text

    # Split on "diff --git" keeping delimiters conceptually
    chunks: list[str] = []
    positions = [m.start() for m in _DIFF_FILE_HEADER.finditer(diff_text)]
    if not positions:
        return diff_text

    positions.append(len(diff_text))
    for idx in range(len(positions) - 1):
        start, end = positions[idx], positions[idx + 1]
        chunk = diff_text[start:end]
        header = _DIFF_FILE_HEADER.match(chunk)
        if not header:
            chunks.append(chunk)
            continue
        path_a, path_b = header.group(1), header.group(2)
        if _should_ignore(path_a, ignore_patterns) or _should_ignore(path_b, ignore_patterns):
            continue
        chunks.append(chunk)
    return "".join(chunks)


def get_staged_diff(
    cwd: Path | None = None,
    *,
    ignore_patterns: tuple[str, ...] | list[str] | None = None,
    max_chars: int | None = None,
) -> tuple[str, bool]:
    """Return (diff_text, truncated). Empty string if nothing staged / all ignored."""
    ensure_repo(cwd)
    result = run_git("diff", "--cached", "--no-color", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to get staged diff")

    diff = result.stdout
    if ignore_patterns:
        diff = filter_diff_by_ignore(diff, ignore_patterns)

    truncated = False
    if max_chars is not None and len(diff) > max_chars:
        diff = (
            diff[:max_chars]
            + "\n\n... [diff truncated by gai due to size limit] ...\n"
        )
        truncated = True
    return diff, truncated


def commit(message: str, cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    if not message.strip():
        raise GitError("commit message must not be empty")
    result = run_git("commit", "-m", message, cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or "git commit failed")


def short_status(cwd: Path | None = None) -> str:
    ensure_repo(cwd)
    result = run_git("status", "--short", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git status failed")
    return result.stdout.strip()


@dataclass(frozen=True)
class CommitInfo:
    hash: str
    author_name: str
    author_email: str
    date: str
    subject: str
    body: str = ""
    shortstat: str = ""

    def to_dict(self) -> dict:
        return {
            "hash": self.hash,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "date": self.date,
            "subject": self.subject,
            "body": self.body,
            "shortstat": self.shortstat,
        }


_RELATIVE_SINCE = re.compile(r"^(\d+)\s*([dwmy])$", re.IGNORECASE)
_COMMIT_MARKER = "===GAI_COMMIT==="


def resolve_since(value: str | None) -> str | None:
    """Normalize --since: '7d'/'1w'/'2026-09-01' → git --since argument."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    rel = _RELATIVE_SINCE.match(text)
    if not rel:
        return text

    amount = int(rel.group(1))
    unit = rel.group(2).lower()
    unit_map = {
        "d": "days",
        "w": "weeks",
        "m": "months",
        "y": "years",
    }
    return f"{amount} {unit_map[unit]} ago"


def current_author_filter(cwd: Path | None = None) -> str:
    """Build --author filter for the current git user (email preferred)."""
    ensure_repo(cwd)
    email = run_git("config", "user.email", cwd=cwd)
    name = run_git("config", "user.name", cwd=cwd)
    if email.returncode == 0 and email.stdout.strip():
        return email.stdout.strip()
    if name.returncode == 0 and name.stdout.strip():
        return name.stdout.strip()
    raise GitError(
        "Cannot resolve current user. Set git user.email/user.name "
        "or pass --author explicitly."
    )


def get_commits(
    cwd: Path | None = None,
    *,
    since: str | None = None,
    until: str | None = None,
    author: str | None = None,
    max_count: int = 100,
    include_stat: bool = True,
    include_merges: bool = False,
) -> list[CommitInfo]:
    """Fetch commit history for work-report summarization."""
    ensure_repo(cwd)
    if max_count <= 0:
        raise GitError("max_count must be positive")

    pretty = (
        f"{_COMMIT_MARKER}%n"
        "%H%n"
        "%an%n"
        "%ae%n"
        "%ad%n"
        "%s"
    )
    args = [
        "log",
        f"--pretty=format:{pretty}",
        "--date=short",
        f"-n{max_count}",
    ]
    if not include_merges:
        args.append("--no-merges")
    if include_stat:
        args.append("--shortstat")
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if author:
        args.append(f"--author={author}")

    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git log failed")

    return _parse_commit_log(result.stdout)


def _parse_commit_log(raw: str) -> list[CommitInfo]:
    if not raw.strip():
        return []

    commits: list[CommitInfo] = []
    chunks = raw.split(_COMMIT_MARKER)
    for chunk in chunks:
        block = chunk.strip()
        if not block:
            continue
        nonempty = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(nonempty) < 5:
            continue

        commit_hash = nonempty[0]
        author_name = nonempty[1]
        author_email = nonempty[2]
        date = nonempty[3]
        subject = nonempty[4]
        shortstat = ""
        for ln in nonempty[5:]:
            if "file changed" in ln or "files changed" in ln:
                shortstat = ln
                break

        commits.append(
            CommitInfo(
                hash=commit_hash,
                author_name=author_name,
                author_email=author_email,
                date=date,
                subject=subject,
                shortstat=shortstat,
            )
        )
    return commits


def format_commits_for_prompt(
    commits: list[CommitInfo],
    *,
    max_chars: int | None = None,
) -> tuple[str, bool]:
    """Render commits into a compact text block for the LLM."""
    lines: list[str] = []
    for c in commits:
        short = c.hash[:8] if c.hash else ""
        lines.append(f"- [{c.date}] {short} {c.author_name}: {c.subject}")
        if c.shortstat:
            lines.append(f"  stat: {c.shortstat}")

    text = "\n".join(lines)
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars] + "\n\n... [commit list truncated by gai] ...\n"
        truncated = True
    return text, truncated
