"""Local workspace: status, staged diff, add/commit/unadd/uncommit."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from gai.common.git.core import GitError, ensure_repo, run_git

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
        raise GitError("commit message must not be empty", code="empty_message")
    result = run_git("commit", "-m", message, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git commit failed",
            code="commit_failed",
        )


def add(paths: list[str] | tuple[str, ...] | None = None, cwd: Path | None = None) -> None:
    """Stage files via `git add`. Defaults to `.` when paths is empty.

    Explicit paths that are gitignored or under project ``.gai/`` are skipped so
    splitflow/devflow batches never fail with ``paths are ignored by .gitignore``.
    If every path is skipped, this is a no-op (caller may then see an empty index).
    """
    ensure_repo(cwd)
    targets = [p for p in (paths or []) if str(p).strip()]
    if not targets:
        targets = ["."]
    if targets != ["."]:
        targets = filter_addable_paths(targets, cwd=cwd)
        if not targets:
            return
    result = run_git("add", "--", *targets, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git add failed",
            code="add_failed",
        )


def unadd(paths: list[str] | tuple[str, ...] | None = None, cwd: Path | None = None) -> None:
    """Unstage files via `git restore --staged`. Defaults to `.` when paths is empty."""
    ensure_repo(cwd)
    if not has_staged_changes(cwd):
        raise GitError("nothing staged to unadd", code="nothing_to_unadd")
    targets = [p for p in (paths or []) if str(p).strip()]
    if not targets:
        targets = ["."]
    result = run_git("restore", "--staged", "--", *targets, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git restore --staged failed",
            code="unadd_failed",
        )


def last_commit_subject(cwd: Path | None = None) -> str | None:
    """Return the latest commit subject, or None if no commits."""
    ensure_repo(cwd)
    result = run_git("log", "-1", "--pretty=format:%s", cwd=cwd)
    if result.returncode != 0:
        return None
    subject = (result.stdout or "").strip()
    return subject or None


def uncommit(cwd: Path | None = None) -> str:
    """Undo the latest commit with soft reset. Returns undone commit subject."""
    ensure_repo(cwd)
    subject = last_commit_subject(cwd)
    if subject is None:
        raise GitError(
            "no commit to undo (repository has no commits?)",
            code="no_commit",
        )
    result = run_git("reset", "--soft", "HEAD~1", cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git reset --soft HEAD~1 failed",
            code="uncommit_failed",
        )
    return subject


def short_status(cwd: Path | None = None) -> str:
    ensure_repo(cwd)
    result = run_git("status", "--short", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git status failed")
    return result.stdout.strip()


def porcelain_status(cwd: Path | None = None) -> str:
    """Raw ``git status --porcelain`` (includes untracked)."""
    ensure_repo(cwd)
    result = run_git("status", "--porcelain", "-u", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git status --porcelain failed")
    return result.stdout


@dataclass(frozen=True)
class ChangeEntry:
    """One path from ``git status --porcelain``."""

    path: str
    index: str
    worktree: str

    @property
    def ignored(self) -> bool:
        """True for ``!!`` ignored entries (only present with ``--ignored``)."""
        return self.index == "!" and self.worktree == "!"

    @property
    def staged(self) -> bool:
        return bool(self.index.strip()) and self.index not in {"?", "!"}

    @property
    def unstaged(self) -> bool:
        return bool(self.worktree.strip()) and self.worktree not in {"?", "!"}

    @property
    def untracked(self) -> bool:
        return self.index == "?" and self.worktree == "?"


def is_local_gai_path(path: str) -> bool:
    """True for project-local ``.gai/`` runtime artifacts (logs, HTML reports)."""
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm == ".gai" or norm.startswith(".gai/")


def is_path_ignored(path: str, cwd: Path | None = None) -> bool:
    """True when ``git check-ignore`` says the path matches an ignore rule.

    Tracked files that happen to match a pattern still return False here only
    when git does not consider them ignored for add purposes; ``check-ignore``
    reports pattern matches for untracked paths. Exit codes: 0=ignored,
    1=not ignored, 128=error (treated as not ignored so callers can still try).
    """
    if not str(path).strip() or path.strip() == ".":
        return False
    result = run_git("check-ignore", "-q", "--", path, cwd=cwd)
    return result.returncode == 0


def filter_addable_paths(
    paths: list[str] | tuple[str, ...] | None,
    cwd: Path | None = None,
    *,
    drop_local_gai: bool = True,
) -> list[str]:
    """Drop gitignored / local ``.gai/`` paths so explicit ``git add`` won't fail.

    ``.`` is kept as-is (``git add .`` already skips ignored files silently).
    """
    out: list[str] = []
    for raw in paths or []:
        path = str(raw or "").strip()
        if not path:
            continue
        if path == ".":
            if path not in out:
                out.append(path)
            continue
        if drop_local_gai and is_local_gai_path(path):
            continue
        if is_path_ignored(path, cwd=cwd):
            continue
        if path not in out:
            out.append(path)
    return out


def list_change_entries(cwd: Path | None = None) -> list[ChangeEntry]:
    """Parse porcelain status into path entries (rename uses the new path)."""
    raw = porcelain_status(cwd)
    entries: list[ChangeEntry] = []
    for line in raw.splitlines():
        if not line:
            continue
        if len(line) < 3:
            continue
        index, worktree, rest = line[0], line[1], line[2:]
        path = rest.lstrip()
        # Rename / copy in porcelain: "R  old -> new"
        if " -> " in path and (index in {"R", "C"} or worktree in {"R", "C"}):
            path = path.split(" -> ", 1)[1].strip()
        path = path.strip().strip('"')
        if not path:
            continue
        entry = ChangeEntry(path=path, index=index, worktree=worktree)
        if entry.ignored or is_local_gai_path(path):
            continue
        entries.append(entry)
    return entries


def get_unstaged_diff(
    cwd: Path | None = None,
    *,
    ignore_patterns: tuple[str, ...] | list[str] | None = None,
    max_chars: int | None = None,
) -> tuple[str, bool]:
    """Return unstaged worktree diff (+ untracked file list), optionally truncated."""
    ensure_repo(cwd)
    result = run_git("diff", "--no-color", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to get unstaged diff")
    diff = result.stdout or ""
    untracked = run_git("ls-files", "--others", "--exclude-standard", cwd=cwd)
    if untracked.returncode == 0 and untracked.stdout.strip():
        names = [ln.strip() for ln in untracked.stdout.splitlines() if ln.strip()]
        if names:
            diff += "\n\n# Untracked files:\n" + "\n".join(f"+ {n}" for n in names) + "\n"
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


def is_worktree_dirty(cwd: Path | None = None) -> bool:
    """True when there are uncommitted (staged or unstaged) changes."""
    return bool(short_status(cwd))

