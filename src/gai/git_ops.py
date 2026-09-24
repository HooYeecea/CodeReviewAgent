"""Thin wrappers around system git via subprocess."""

from __future__ import annotations

import fnmatch
import re
import shlex
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


def run_git(*args: str, cwd: Path | None = None) -> GitResult:
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


def add(paths: list[str] | tuple[str, ...] | None = None, cwd: Path | None = None) -> None:
    """Stage files via `git add`. Defaults to `.` when paths is empty."""
    ensure_repo(cwd)
    targets = [p for p in (paths or []) if str(p).strip()]
    if not targets:
        targets = ["."]
    result = run_git("add", "--", *targets, cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or "git add failed")


def unadd(paths: list[str] | tuple[str, ...] | None = None, cwd: Path | None = None) -> None:
    """Unstage files via `git restore --staged`. Defaults to `.` when paths is empty."""
    ensure_repo(cwd)
    if not has_staged_changes(cwd):
        raise GitError("nothing staged to unadd")
    targets = [p for p in (paths or []) if str(p).strip()]
    if not targets:
        targets = ["."]
    result = run_git("restore", "--staged", "--", *targets, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git restore --staged failed"
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
        raise GitError("no commit to undo (repository has no commits?)")
    result = run_git("reset", "--soft", "HEAD~1", cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git reset --soft HEAD~1 failed"
        )
    return subject


def short_status(cwd: Path | None = None) -> str:
    ensure_repo(cwd)
    result = run_git("status", "--short", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git status failed")
    return result.stdout.strip()


def list_remotes(cwd: Path | None = None) -> list[str]:
    ensure_repo(cwd)
    result = run_git("remote", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to list remotes")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_current_branch(cwd: Path | None = None) -> str:
    ensure_repo(cwd)
    result = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to get current branch")
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        raise GitError("detached HEAD; checkout a branch before pushing")
    return branch


def get_upstream_ref(cwd: Path | None = None) -> str | None:
    """Return upstream like 'origin/main', or None if unset."""
    ensure_repo(cwd)
    result = run_git(
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
        cwd=cwd,
    )
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    return ref or None


def choose_remote(remotes: list[str], preferred: str | None = None) -> str:
    """Pick remote name. Prefer explicit, then origin, then sole remote."""
    if not remotes:
        raise GitError(
            "No git remote configured. Add one first, e.g. "
            "`git remote add origin <url>`."
        )
    if preferred:
        name = preferred.strip()
        if name not in remotes:
            raise GitError(
                f"Remote '{name}' not found. Available: {', '.join(remotes)}"
            )
        return name
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    raise GitError(
        "Multiple remotes found and none named 'origin'. "
        f"Pass --remote explicitly. Available: {', '.join(remotes)}"
    )


@dataclass(frozen=True)
class PushPlan:
    remote: str
    branch: str
    upstream: str | None
    set_upstream: bool
    args: tuple[str, ...]

    def describe(self) -> str:
        return " ".join(["git", "push", *self.args])


@dataclass(frozen=True)
class SyncCheck:
    remote: str
    branch: str
    upstream: str | None
    ahead: int
    behind: int


def fetch_remote(remote: str, cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    result = run_git("fetch", remote, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            (result.stderr or result.stdout or f"git fetch {remote} failed").strip()
        )


def _rev_list_count(range_spec: str, cwd: Path | None = None) -> int:
    result = run_git("rev-list", "--count", range_spec, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            (result.stderr or result.stdout or f"git rev-list failed for {range_spec}").strip()
        )
    text = (result.stdout or "").strip()
    try:
        return int(text or "0")
    except ValueError as exc:
        raise GitError(f"unexpected rev-list output: {text!r}") from exc


def _remote_branch_exists(remote: str, branch: str, cwd: Path | None = None) -> bool:
    result = run_git("rev-parse", "--verify", f"refs/remotes/{remote}/{branch}", cwd=cwd)
    return result.returncode == 0


def check_sync(
    cwd: Path | None = None,
    *,
    remote: str | None = None,
    do_fetch: bool = True,
) -> SyncCheck:
    """Fetch (optional) and compute how many commits are ahead/behind remote."""
    remotes = list_remotes(cwd)
    remote_name = choose_remote(remotes, preferred=remote)
    branch = get_current_branch(cwd)
    if do_fetch:
        fetch_remote(remote_name, cwd)

    upstream = get_upstream_ref(cwd)
    remote_ref = f"{remote_name}/{branch}"

    if upstream:
        ahead = _rev_list_count(f"{upstream}..HEAD", cwd)
        behind = _rev_list_count(f"HEAD..{upstream}", cwd)
    elif _remote_branch_exists(remote_name, branch, cwd):
        ahead = _rev_list_count(f"{remote_ref}..HEAD", cwd)
        behind = _rev_list_count(f"HEAD..{remote_ref}", cwd)
    else:
        # No remote branch yet: everything local is outgoing; nothing incoming.
        ahead = _rev_list_count("HEAD", cwd)
        behind = 0

    return SyncCheck(
        remote=remote_name,
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
    )


def plan_push(
    cwd: Path | None = None,
    *,
    remote: str | None = None,
    set_upstream: bool | None = None,
) -> PushPlan:
    """Build the git push argv after validating remotes / branch."""
    remotes = list_remotes(cwd)
    remote_name = choose_remote(remotes, preferred=remote)
    branch = get_current_branch(cwd)
    upstream = get_upstream_ref(cwd)

    need_upstream = upstream is None
    if set_upstream is True:
        need_upstream = True
    elif set_upstream is False and upstream is None:
        raise GitError(
            f"Branch '{branch}' has no upstream. "
            "Re-run with --set-upstream (or omit --no-set-upstream)."
        )

    if need_upstream:
        args = ("-u", remote_name, branch)
    else:
        args = (remote_name, branch)

    return PushPlan(
        remote=remote_name,
        branch=branch,
        upstream=upstream,
        set_upstream=need_upstream,
        args=args,
    )


class NothingToPush(GitError):
    """Raised when local branch has no commits ahead of remote."""


class NothingToPull(GitError):
    """Raised when remote has no commits to pull."""


def push(
    cwd: Path | None = None,
    *,
    remote: str | None = None,
    set_upstream: bool | None = None,
    check: SyncCheck | None = None,
) -> PushPlan:
    """Push current branch to remote. Returns the plan that was executed."""
    plan = plan_push(cwd, remote=remote, set_upstream=set_upstream)
    sync = check or check_sync(cwd, remote=plan.remote, do_fetch=True)
    if sync.ahead <= 0:
        raise NothingToPush(
            f"Nothing to push: {plan.remote}/{plan.branch} is up to date "
            f"(ahead={sync.ahead})."
        )

    result = run_git("push", *plan.args, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git push failed").strip()
        raise GitError(detail)

    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "everything up-to-date" in combined:
        raise NothingToPush(
            f"Nothing to push: {plan.remote}/{plan.branch} is already up to date."
        )
    return plan


def pull(
    cwd: Path | None = None,
    *,
    remote: str | None = None,
    check: SyncCheck | None = None,
) -> SyncCheck:
    """Pull from remote after verifying there is something to pull."""
    sync = check or check_sync(cwd, remote=remote, do_fetch=True)
    if sync.behind <= 0:
        raise NothingToPull(
            f"Nothing to pull: already up to date with "
            f"{sync.remote}/{sync.branch} (behind={sync.behind})."
        )

    if sync.upstream:
        result = run_git("pull", cwd=cwd)
    else:
        result = run_git("pull", sync.remote, sync.branch, cwd=cwd)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git pull failed").strip()
        raise GitError(detail)

    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "already up to date" in combined or "already up-to-date" in combined:
        raise NothingToPull(
            f"Nothing to pull: already up to date with {sync.remote}/{sync.branch}."
        )
    return sync


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
_ALLTIME_TOKENS = frozenset({"alltime", "all-time", "all_time", "all"})


def is_alltime_token(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _ALLTIME_TOKENS


def resolve_since(value: str | None) -> str | None:
    """Normalize --since: '7d'/'1w'/'2026-09-01'/'alltime' → git --since argument.

    Returns None for empty values or alltime tokens (no --since filter).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if is_alltime_token(text):
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
