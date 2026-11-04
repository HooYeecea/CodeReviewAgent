"""Local workspace: status, staged diff, add/commit/unadd/uncommit."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from gai.common.git.core import GitError, ensure_repo, run_git

# Process-local caches: invalidated whenever the index / HEAD mutates via gai.
_STAGED_DIFF_CACHE: dict[tuple[object, ...], tuple[str, bool]] = {}
_UNSTAGED_DIFF_CACHE: dict[tuple[object, ...], tuple[str, bool]] = {}
_HAS_STAGED_CACHE: dict[object, bool] = {}


def clear_diff_cache() -> None:
    """Drop cached staged/unstaged diffs (call after add/unadd/commit/reset)."""
    _STAGED_DIFF_CACHE.clear()
    _UNSTAGED_DIFF_CACHE.clear()
    _HAS_STAGED_CACHE.clear()


def _cwd_key(cwd: Path | None) -> str:
    """Stable cache key; ``cwd=None`` means the process current directory."""
    root = Path(cwd) if cwd is not None else Path.cwd()
    return str(root.resolve())


@dataclass(frozen=True)
class StagedSnapshot:
    """Index contents and the HEAD against which those contents were reviewed."""

    tree: str
    head: str
    ref: str


def staged_snapshot(cwd: Path | None = None) -> StagedSnapshot:
    tree = run_git("write-tree", cwd=cwd)
    if tree.returncode != 0:
        raise GitError(tree.stderr.strip() or "Cannot snapshot the index")
    head = run_git("rev-parse", "--verify", "HEAD", cwd=cwd)
    ref = run_git("symbolic-ref", "-q", "HEAD", cwd=cwd)
    return StagedSnapshot(
        tree.stdout.strip(),
        head.stdout.strip() if head.returncode == 0 else "",
        ref.stdout.strip() if ref.returncode == 0 else "",
    )


def assert_staged_snapshot(expected: StagedSnapshot, cwd: Path | None = None) -> None:
    if staged_snapshot(cwd) != expected:
        raise GitError(
            "Staged changes or HEAD changed since review. Run the review again before committing.",
            code="review_changed",
        )


def has_staged_changes(cwd: Path | None = None) -> bool:
    ensure_repo(cwd)
    key = (_cwd_key(cwd), staged_snapshot(cwd))
    if key in _HAS_STAGED_CACHE:
        return _HAS_STAGED_CACHE[key]
    # --quiet: exit 0 if no diff, 1 if there is a diff, >1 on error
    result = run_git("diff", "--cached", "--quiet", cwd=cwd)
    if result.returncode == 0:
        _HAS_STAGED_CACHE[key] = False
        return False
    if result.returncode == 1:
        _HAS_STAGED_CACHE[key] = True
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


_DIFF_FILE_HEADER = re.compile(r"^diff --git .*?$", re.MULTILINE)
_PATCH_OPTIONS = ("--no-color", "--no-ext-diff", "--no-textconv", "--no-relative",
                  "--src-prefix=a/", "--dst-prefix=b/")


def filter_diff_by_ignore(diff_text: str, ignore_patterns: tuple[str, ...] | list[str]) -> str:
    """Drop whole file sections whose path matches ignore patterns."""
    if not diff_text.strip() or not ignore_patterns:
        return diff_text

    # Split on "diff --git" keeping delimiters conceptually
    chunks: list[str] = []
    positions = [m.start() for m in _DIFF_FILE_HEADER.finditer(diff_text)]
    if not positions or diff_text[:positions[0]].strip():
        raise GitError("无法识别 Diff 路径，已停止发送审查 / Cannot safely filter diff paths", code="diff_paths")

    positions.append(len(diff_text))
    for idx in range(len(positions) - 1):
        start, end = positions[idx], positions[idx + 1]
        chunk = diff_text[start:end]
        from gai.common.git.diff_paths import patch_paths
        try:
            path_a, path_b = patch_paths(chunk)
        except ValueError as exc:
            raise GitError("无法识别 Diff 路径，已停止发送审查 / Cannot safely filter diff paths", code="diff_paths") from exc
        if _should_ignore(path_a, ignore_patterns) or _should_ignore(path_b, ignore_patterns):
            continue
        chunks.append(chunk)
    return "".join(chunks)


def get_staged_diff(
    cwd: Path | None = None,
    *,
    ignore_patterns: tuple[str, ...] | list[str] | None = None,
    max_chars: int | None = None,
    snapshot: StagedSnapshot | None = None,
) -> tuple[str, bool]:
    """Return (diff_text, truncated). Empty string if nothing staged / all ignored.

    Cache entries are tied to index contents and HEAD, including external edits.
    """
    ensure_repo(cwd)
    patterns = tuple(ignore_patterns or ())
    snapshot = snapshot or staged_snapshot(cwd)
    assert_staged_snapshot(snapshot, cwd)
    cache_key = (_cwd_key(cwd), patterns, max_chars, snapshot)
    hit = _STAGED_DIFF_CACHE.get(cache_key)
    if hit is not None:
        return hit

    result = run_git("diff", "--cached", *_PATCH_OPTIONS, cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to get staged diff")
    assert_staged_snapshot(snapshot, cwd)

    diff = result.stdout
    if patterns:
        diff = filter_diff_by_ignore(diff, patterns)

    truncated = False
    if max_chars is not None and len(diff) > max_chars:
        diff = (
            diff[:max_chars]
            + "\n\n... [diff truncated by gai due to size limit] ...\n"
        )
        truncated = True
    out = (diff, truncated)
    _STAGED_DIFF_CACHE[cache_key] = out
    return out


def commit(
    message: str, cwd: Path | None = None, *,
    expected_snapshot: StagedSnapshot | None = None,
) -> None:
    ensure_repo(cwd)
    if not message.strip():
        raise GitError("commit message must not be empty", code="empty_message")
    if expected_snapshot is not None:
        assert_staged_snapshot(expected_snapshot, cwd)
        # A resolved merge legitimately has more than one parent. Capture its
        # intended parents before hooks run, then compare the actual commit.
        parents = [expected_snapshot.head] if expected_snapshot.head else []
        merge_path = run_git("rev-parse", "--git-path", "MERGE_HEAD", cwd=cwd)
        if merge_path.returncode:
            raise GitError(merge_path.stderr.strip() or "Cannot inspect merge state")
        try:
            merge_heads = ((cwd or Path.cwd()) / merge_path.stdout.strip()).read_text(encoding="ascii")
        except FileNotFoundError:
            merge_heads = ""
        except (OSError, UnicodeError) as exc:
            raise GitError("Cannot inspect merge parents before committing") from exc
        parents.extend(merge_heads.split())
    result = run_git("commit", "-m", message, cwd=cwd)
    clear_diff_cache()
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git commit failed",
            code="commit_failed",
        )
    if expected_snapshot is not None:
        try:
            actual = staged_snapshot(cwd)
            details = run_git("show", "-s", "--format=%H%x00%T%x00%P", "HEAD", cwd=cwd)
        except GitError as exc:
            raise GitError(
                "提交已创建，但无法完成提交后核验；已停止后续操作，请先检查现有提交。 / "
                "Commit created but verification failed; inspect the existing commit before retrying.",
                code="commit_review_mismatch",
            ) from exc
        fields = details.stdout.strip().split("\0")
        if (details.returncode or len(fields) != 3
                or fields[0] != actual.head or actual.head == expected_snapshot.head
                or fields[1] != expected_snapshot.tree or fields[2].split() != parents
                or actual.ref != expected_snapshot.ref or actual.tree != expected_snapshot.tree):
            raise GitError(
                "提交已创建，但提交内容、父提交、分支或暂存区与审查版本不一致；"
                "已停止后续操作，请检查现有提交，不要直接重复提交。 / "
                "Commit created but differs from the reviewed state; subsequent actions stopped. Inspect before retrying.",
                code="commit_review_mismatch",
            )


def add(paths: list[str] | tuple[str, ...] | None = None, cwd: Path | None = None) -> None:
    """Stage files via `git add`. Defaults to `.` when paths is empty.

    Explicit paths that are gitignored or under project ``.gai/`` are skipped so
    splitflow/devflow batches never fail with ``paths are ignored by .gitignore``.
    If every path is skipped, this is a no-op (caller may then see an empty index).
    """
    ensure_repo(cwd)
    targets = [p for p in (paths or []) if str(p)]
    if not targets:
        targets = ["."]
    if targets != ["."]:
        targets = filter_addable_paths(targets, cwd=cwd)
        if not targets:
            return
    result = run_git("add", "--", *targets, cwd=cwd)
    clear_diff_cache()
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
    targets = [p for p in (paths or []) if str(p)]
    if not targets:
        targets = ["."]
    result = run_git("restore", "--staged", "--", *targets, cwd=cwd)
    clear_diff_cache()
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
    clear_diff_cache()
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
        path = str(raw or "")
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
    ensure_repo(cwd)
    result = run_git("status", "--porcelain", "-z", "-uall", cwd=cwd)
    if result.returncode:
        raise GitError(result.stderr.strip() or "Cannot read workspace status")
    fields = iter(result.stdout.split("\0"))
    entries: list[ChangeEntry] = []
    for line in fields:
        if not line:
            continue
        if len(line) < 3:
            continue
        index, worktree, path = line[0], line[1], line[3:]
        # In -z mode the destination comes first, followed by the source.
        if index in {"R", "C"} or worktree in {"R", "C"}:
            if next(fields, None) is None:
                raise GitError("Incomplete rename status")
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
    patterns = tuple(ignore_patterns or ())
    result = run_git("diff", *_PATCH_OPTIONS, cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to get unstaged diff")
    diff = result.stdout or ""
    if patterns:
        diff = filter_diff_by_ignore(diff, patterns)
    untracked = run_git("ls-files", "--others", "--exclude-standard", "--full-name", "-z", cwd=cwd)
    if untracked.returncode == 0 and untracked.stdout.strip():
        names = [name for name in untracked.stdout.split("\0") if name and not _should_ignore(name, patterns)]
        if names:
            diff += "\n\n# Untracked files:\n" + "\n".join(f"+ {n}" for n in names) + "\n"
    truncated = False
    if max_chars is not None and len(diff) > max_chars:
        diff = (
            diff[:max_chars]
            + "\n\n... [diff truncated by gai due to size limit] ...\n"
        )
        truncated = True
    out = (diff, truncated)
    return out


def is_worktree_dirty(cwd: Path | None = None) -> bool:
    """True when there are uncommitted (staged or unstaged) changes."""
    return bool(short_status(cwd))

