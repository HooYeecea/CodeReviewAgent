"""Remote sync: fetch / push / pull planning and classification."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from gai.common.git.core import GitError, ensure_repo, run_git

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
    head: str
    urls: tuple[str, ...]

    def describe(self) -> str:
        return " ".join(["git", "push", *self.args])


@dataclass(frozen=True)
class SyncCheck:
    remote: str
    branch: str
    upstream: str | None
    ahead: int
    behind: int
    target_branch: str = ""
    push_plan: PushPlan | None = None

    @property
    def remote_branch(self) -> str:
        return self.target_branch or self.branch


def _sync_target(
    cwd: Path | None, remote: str | None, *, for_push: bool,
) -> tuple[str, str, str | None, str]:
    remote_name = choose_remote(list_remotes(cwd), preferred=remote)
    branch = get_current_branch(cwd)
    upstream = get_upstream_ref(cwd)
    target_branch = branch
    # Push explicitly sends the current branch. Pull may follow a differently
    # named upstream branch, but only on the selected remote.
    if not for_push and upstream and upstream.startswith(remote_name + "/"):
        target_branch = upstream[len(remote_name) + 1:]
    return remote_name, branch, upstream, target_branch


def _validate_sync_target(
    sync: SyncCheck, cwd: Path | None, remote: str | None, *, for_push: bool,
) -> None:
    name, branch, _, target = _sync_target(cwd, remote or sync.remote, for_push=for_push)
    if (name, branch, target) != (sync.remote, sync.branch, sync.remote_branch):
        raise GitError("Sync target changed after checking", code="sync_target_changed")


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
    for_push: bool = False,
    push_plan: PushPlan | None = None,
) -> SyncCheck:
    """Check incoming history, or live outgoing history at every push URL.

    Push checks always query the actual destinations, even with do_fetch=False;
    fetch tracking refs cannot describe a remote with a separate push URL.
    """
    if for_push:
        plan = push_plan or plan_push(cwd, remote=remote)
        _validate_push_plan(plan, cwd, remote)
        counts = [_push_counts(plan, url, cwd) for url in plan.urls]
        _validate_push_plan(plan, cwd, remote)
        return SyncCheck(plan.remote, plan.branch, plan.upstream,
                         max(a for a, _ in counts), max(b for _, b in counts),
                         plan.branch, plan)
    remote_name, branch, upstream, target_branch = _sync_target(
        cwd, remote, for_push=for_push,
    )
    if do_fetch:
        fetch_remote(remote_name, cwd)

    remote_ref = f"refs/remotes/{remote_name}/{target_branch}"

    if _remote_branch_exists(remote_name, target_branch, cwd):
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
        target_branch=target_branch,
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

    head = _push_head(cwd)
    urls = _push_urls(remote_name, cwd)
    # Display the remote alias, never credential-bearing URLs. Execution uses
    # the pinned URLs and SHA below; -u cannot infer a local branch from a SHA.
    args = (remote_name, f"{head}:refs/heads/{branch}")

    return PushPlan(
        remote=remote_name,
        branch=branch,
        upstream=upstream,
        set_upstream=need_upstream,
        args=args,
        head=head,
        urls=urls,
    )


def _push_head(cwd: Path | None) -> str:
    result = run_git("rev-parse", "--verify", "HEAD", cwd=cwd)
    if result.returncode:
        raise GitError("Cannot resolve the commit to push", code="push_failed")
    return result.stdout.strip()


def _push_urls(remote: str, cwd: Path | None) -> tuple[str, ...]:
    result = run_git("remote", "get-url", "--push", "--all", remote, cwd=cwd)
    urls = tuple(dict.fromkeys(result.stdout.splitlines()))
    if result.returncode or not urls:
        raise GitError("Cannot resolve push destinations", code="push_failed")
    return urls


def _validate_push_plan(plan: PushPlan, cwd: Path | None, remote: str | None = None) -> None:
    if ((remote is not None and remote != plan.remote)
            or get_current_branch(cwd) != plan.branch
            or _push_head(cwd) != plan.head
            or _push_urls(plan.remote, cwd) != plan.urls):
        raise GitError("推送的提交、分支或地址已变化，请重新检查。 / "
                       "Push source or destination changed; check again.",
                       code="sync_target_changed")


def _push_remote_error(result, action: str) -> GitError:
    code = classify_remote_failure(result.stderr or result.stdout)
    # URL arguments and Git's output can contain credentials.
    return GitError(f"{action}; check the remote and retry (some destinations may already be updated).",
                    code="push_failed" if code == "generic" else code)


def _push_counts(plan: PushPlan, url: str, cwd: Path | None) -> tuple[int, int]:
    """Compare the pinned source to a live destination without changing FETCH_HEAD."""
    ref = f"refs/heads/{plan.branch}"
    advertised = run_git("ls-remote", "--exit-code", "--refs", "--", url, ref,
                         cwd=cwd, trace=False)
    if advertised.returncode == 2:
        return _rev_list_count(plan.head, cwd), 0
    if advertised.returncode:
        raise _push_remote_error(advertised, "Cannot check push destination")
    fields = advertised.stdout.split()
    if len(fields) != 2 or fields[1] != ref:
        raise GitError("Unexpected response from push destination", code="push_failed")
    if fields[0] == plan.head:
        return 0, 0
    temporary_ref = f"refs/gai/push-check/{uuid4().hex}"
    try:
        fetched = run_git("fetch", "--no-tags", "--no-write-fetch-head", "--", url,
                          f"+{ref}:{temporary_ref}", cwd=cwd, trace=False)
        if fetched.returncode:
            raise _push_remote_error(fetched, "Cannot inspect push destination")
        return (_rev_list_count(f"{temporary_ref}..{plan.head}", cwd),
                _rev_list_count(f"{plan.head}..{temporary_ref}", cwd))
    finally:
        run_git("update-ref", "-d", temporary_ref, cwd=cwd, trace=False)


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
    if check:
        _validate_sync_target(check, cwd, remote, for_push=True)
    plan = (check.push_plan if check else None) or plan_push(
        cwd, remote=remote or (check.remote if check else None), set_upstream=set_upstream)
    if set_upstream is True:
        plan = replace(plan, set_upstream=True)
    elif set_upstream is False:
        if plan.upstream is None:
            raise GitError("Branch has no upstream; omit --no-set-upstream.", code="no_upstream")
        plan = replace(plan, set_upstream=False)
    _validate_push_plan(plan, cwd, remote)
    # Recheck all destinations before the first write, including callers that
    # supply a pull-oriented SyncCheck or a stale ahead count.
    counts = [_push_counts(plan, url, cwd) for url in plan.urls]
    if any(ahead and behind for ahead, behind in counts):
        raise GitError("Remote history has diverged; pull and review before pushing.", code="rejected")
    if not any(ahead for ahead, _ in counts):
        raise NothingToPush(
            f"Nothing to push: {plan.remote}/{plan.branch} already contains the commit."
        )

    for url, (ahead, _) in zip(plan.urls, counts):
        _validate_push_plan(plan, cwd, remote)
        if ahead:
            result = run_git("push", "--no-follow-tags", "--no-mirror", "--", url,
                             f"{plan.head}:refs/heads/{plan.branch}", cwd=cwd, trace=False)
            if result.returncode:
                raise _push_remote_error(result, "Push failed")
        if _push_counts(plan, url, cwd)[0]:
            raise GitError("Remote does not contain the checked commit; inspect before retrying.",
                           code="push_failed")
    _validate_push_plan(plan, cwd, remote)
    if plan.set_upstream:
        for key, value in ((f"branch.{plan.branch}.remote", plan.remote),
                           (f"branch.{plan.branch}.merge", f"refs/heads/{plan.branch}")):
            result = run_git("config", key, value, cwd=cwd)
            if result.returncode:
                raise GitError("Push verified, but upstream configuration failed.", code="push_failed")
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
    _validate_sync_target(sync, cwd, remote, for_push=False)
    if sync.behind <= 0:
        raise NothingToPull(
            f"Nothing to pull: already up to date with "
            f"{sync.remote}/{sync.remote_branch} (behind={sync.behind})."
        )

    # The chosen strategy must override pull.rebase / branch.*.rebase and
    # pull.ff=only. Merge allows fast-forward and keeps existing commit IDs.
    args = ["pull", "--rebase"] if rebase else ["pull", "--no-rebase", "--ff", "--no-edit"]
    result = run_git(*args, sync.remote, f"refs/heads/{sync.remote_branch}", cwd=cwd)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git pull failed").strip()
        code = classify_remote_failure(detail)
        raise GitError(detail, code="pull_failed" if code == "generic" else code)

    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    if "already up to date" in combined or "already up-to-date" in combined:
        raise NothingToPull(
            f"Nothing to pull: already up to date with {sync.remote}/{sync.remote_branch}."
        )
    return sync

