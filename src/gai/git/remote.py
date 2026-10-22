"""Remote sync: fetch / push / pull planning and classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gai.git.core import GitError, ensure_repo, run_git

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
        raise GitError(
            "detached HEAD; checkout a branch before pushing",
            code="detached_head",
        )
    return branch


def current_branch_name(cwd: Path | None = None) -> str:
    """Best-effort branch name for usage logs; empty if unavailable."""
    try:
        result = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, trace=False)
    except GitError:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def count_staged_files(cwd: Path | None = None) -> int:
    """Number of paths in the staged diff (best-effort; 0 on failure)."""
    try:
        result = run_git("diff", "--cached", "--name-only", "--no-color", cwd=cwd, trace=False)
    except GitError:
        return 0
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


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
            "`git remote add origin <url>`.",
            code="no_remote",
        )
    if preferred:
        name = preferred.strip()
        if name not in remotes:
            raise GitError(
                f"Remote '{name}' not found. Available: {', '.join(remotes)}",
                code="remote_not_found",
            )
        return name
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    raise GitError(
        "Multiple remotes found and none named 'origin'. "
        f"Pass --remote explicitly. Available: {', '.join(remotes)}",
        code="multiple_remotes",
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


def classify_remote_failure(detail: str) -> str:
    """Map git remote stderr to a stable error code."""
    text = (detail or "").lower()
    auth_hints = (
        "authentication failed",
        "permission denied",
        "could not read username",
        "invalid username",
        "access denied",
        "403",
        "401",
        "terminal prompts disabled",
        "publickey",
    )
    if any(h in text for h in auth_hints):
        return "auth"
    reject_hints = (
        "non-fast-forward",
        "fetch first",
        "rejected",
        "protected branch",
        "updates were rejected",
    )
    if any(h in text for h in reject_hints):
        return "rejected"
    net_hints = (
        "could not resolve host",
        "failed to connect",
        "connection refused",
        "network is unreachable",
        "timed out",
        "timeout",
        "ssl",
        "tls",
        "unable to access",
    )
    if any(h in text for h in net_hints):
        return "network"
    conflict_hints = (
        "fix conflicts",
        "merge conflict",
        "conflicted",
        "unmerged paths",
        "failed to merge",
        "could not apply",
        "needs merge",
        "you are in the middle of an unresolved merge",
        "resolve your current index first",
    )
    if any(h in text for h in conflict_hints):
        return "pull_conflict"
    dirty_hints = (
        "please commit your changes or stash",
        "would be overwritten",
        "uncommitted changes",
        "your local changes",
    )
    if any(h in text for h in dirty_hints):
        return "dirty_worktree"
    return "generic"


def classify_git_failure(detail: str, *, kind: str = "generic") -> str:
    """Classify local git failures (merge / rebase / switch / stash)."""
    code = classify_remote_failure(detail)
    if code == "pull_conflict":
        if kind == "merge":
            return "merge_conflict"
        if kind == "rebase":
            return "rebase_conflict"
        return "pull_conflict"
    if code != "generic":
        return code
    text = (detail or "").lower()
    if "already exists" in text and kind in {"switch", "branch"}:
        return "branch_exists"
    if "did not match any" in text or "needed a single revision" in text:
        return "branch_not_found"
    if "no local changes to save" in text or "no stash entries" in text:
        return "nothing_to_stash"
    return {
        "merge": "merge_failed",
        "rebase": "rebase_failed",
        "switch": "switch_failed",
        "stash": "stash_failed",
        "branch": "branch_failed",
    }.get(kind, "generic")


def fetch_remote(remote: str, cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    result = run_git("fetch", remote, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"git fetch {remote} failed").strip()
        code = classify_remote_failure(detail)
        raise GitError(detail, code="fetch_failed" if code == "generic" else code)


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
            "Re-run with --set-upstream (or omit --no-set-upstream).",
            code="no_upstream",
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
        code = classify_remote_failure(detail)
        raise GitError(detail, code="push_failed" if code == "generic" else code)

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
    rebase: bool = False,
) -> SyncCheck:
    """Pull from remote after verifying there is something to pull."""
    sync = check or check_sync(cwd, remote=remote, do_fetch=True)
    if sync.behind <= 0:
        raise NothingToPull(
            f"Nothing to pull: already up to date with "
            f"{sync.remote}/{sync.branch} (behind={sync.behind})."
        )

    args: list[str] = ["pull"]
    if rebase:
        args.append("--rebase")
    if sync.upstream:
        result = run_git(*args, cwd=cwd)
    else:
        result = run_git(*args, sync.remote, sync.branch, cwd=cwd)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git pull failed").strip()
        code = classify_remote_failure(detail)
        raise GitError(detail, code="pull_failed" if code == "generic" else code)

    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "already up to date" in combined or "already up-to-date" in combined:
        raise NothingToPull(
            f"Nothing to pull: already up to date with {sync.remote}/{sync.branch}."
        )
    return sync

