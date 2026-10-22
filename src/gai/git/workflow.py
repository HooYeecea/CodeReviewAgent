"""Merge, rebase, branch, switch, stash."""

from __future__ import annotations

from pathlib import Path

from gai.git.core import GitError, ensure_repo, run_git
from gai.git.local import is_worktree_dirty
from gai.git.remote import (
    _rev_list_count,
    classify_git_failure,
    get_current_branch,
)

def ref_exists(ref: str, cwd: Path | None = None) -> bool:
    """True when ``ref`` resolves (branch, tag, or commit-ish)."""
    ensure_repo(cwd)
    result = run_git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd)
    if result.returncode == 0:
        return True
    # Fallback without ^{commit} for some refs.
    result = run_git("rev-parse", "--verify", "--quiet", ref, cwd=cwd)
    return result.returncode == 0


def list_local_branches(cwd: Path | None = None) -> list[str]:
    ensure_repo(cwd)
    result = run_git("branch", "--format=%(refname:short)", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to list branches")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def commits_ahead_of_head(ref: str, cwd: Path | None = None) -> int:
    """How many commits ``ref`` has that HEAD does not (merge preview)."""
    ensure_repo(cwd)
    if not ref_exists(ref, cwd):
        raise GitError(f"ref not found: {ref}", code="branch_not_found")
    return _rev_list_count(f"HEAD..{ref}", cwd)


def _git_dir(cwd: Path | None = None) -> Path:
    ensure_repo(cwd)
    result = run_git("rev-parse", "--git-dir", cwd=cwd, trace=False)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "failed to resolve git dir", code="not_repo")
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        base = Path(cwd) if cwd is not None else Path.cwd()
        path = (base / path).resolve()
    return path


def merge_in_progress(cwd: Path | None = None) -> bool:
    return (_git_dir(cwd) / "MERGE_HEAD").is_file()


def rebase_in_progress(cwd: Path | None = None) -> bool:
    git_dir = _git_dir(cwd)
    return (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir()


def raise_if_sequencer_busy(cwd: Path | None = None) -> None:
    """Block starting a new merge/rebase/switch while one is in progress."""
    if merge_in_progress(cwd):
        raise GitError(
            "A merge is already in progress. Use `gai merge --continue` or `gai merge --abort`.",
            code="merge_in_progress",
        )
    if rebase_in_progress(cwd):
        raise GitError(
            "A rebase is already in progress. Use `gai rebase --continue` or `gai rebase --abort`.",
            code="rebase_in_progress",
        )


def merge_abort(cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    if not merge_in_progress(cwd):
        raise GitError("No merge in progress to abort.", code="no_merge_in_progress")
    result = run_git("merge", "--abort", cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git merge --abort failed").strip()
        raise GitError(detail, code="merge_failed")


def merge_continue(cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    if not merge_in_progress(cwd):
        raise GitError("No merge in progress to continue.", code="no_merge_in_progress")
    result = run_git("-c", "core.editor=true", "merge", "--continue", cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git merge --continue failed").strip()
        code = classify_git_failure(detail, kind="merge")
        raise GitError(detail, code=code if code != "generic" else "merge_failed")


def rebase_abort(cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    if not rebase_in_progress(cwd):
        raise GitError("No rebase in progress to abort.", code="no_rebase_in_progress")
    result = run_git("rebase", "--abort", cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git rebase --abort failed").strip()
        raise GitError(detail, code="rebase_failed")


def rebase_continue(cwd: Path | None = None) -> None:
    ensure_repo(cwd)
    if not rebase_in_progress(cwd):
        raise GitError("No rebase in progress to continue.", code="no_rebase_in_progress")
    result = run_git("-c", "core.editor=true", "rebase", "--continue", cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git rebase --continue failed").strip()
        code = classify_git_failure(detail, kind="rebase")
        raise GitError(detail, code=code if code != "generic" else "rebase_failed")


def merge(
    branch: str,
    cwd: Path | None = None,
    *,
    no_ff: bool = False,
) -> int:
    """Merge ``branch`` into HEAD. Returns commits brought in (best-effort)."""
    ensure_repo(cwd)
    raise_if_sequencer_busy(cwd)
    current = get_current_branch(cwd)
    target = branch.strip()
    if not target:
        raise GitError("merge branch name is required", code="branch_not_found")
    if target == current:
        raise GitError(
            f"already on '{current}'; nothing to merge",
            code="already_on_branch",
        )
    if not ref_exists(target, cwd):
        raise GitError(f"branch/ref not found: {target}", code="branch_not_found")
    ahead = commits_ahead_of_head(target, cwd)
    if ahead <= 0:
        raise GitError(
            f"Already up to date with '{target}' (nothing to merge).",
            code="nothing_to_merge",
        )
    args = ["merge", "--no-edit"]
    if no_ff:
        args.append("--no-ff")
    args.append(target)
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git merge failed").strip()
        code = classify_git_failure(detail, kind="merge")
        raise GitError(detail, code=code if code != "generic" else "merge_failed")
    return ahead


def rebase(onto: str, cwd: Path | None = None) -> int:
    """Rebase current branch onto ``onto``. Returns commit count being replayed."""
    ensure_repo(cwd)
    raise_if_sequencer_busy(cwd)
    current = get_current_branch(cwd)
    target = onto.strip()
    if not target:
        raise GitError("rebase onto ref is required", code="branch_not_found")
    if target == current:
        raise GitError(
            f"cannot rebase '{current}' onto itself",
            code="already_on_branch",
        )
    if not ref_exists(target, cwd):
        raise GitError(f"branch/ref not found: {target}", code="branch_not_found")
    # Commits on HEAD that are not on onto (what rebase will replay).
    replay = _rev_list_count(f"{target}..HEAD", cwd)
    if replay <= 0 and commits_ahead_of_head(target, cwd) <= 0:
        raise GitError(
            f"Already up to date with '{target}' (nothing to rebase).",
            code="nothing_to_rebase",
        )
    result = run_git("rebase", target, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git rebase failed").strip()
        code = classify_git_failure(detail, kind="rebase")
        raise GitError(detail, code=code if code != "generic" else "rebase_failed")
    return replay


def create_branch(
    name: str,
    cwd: Path | None = None,
    *,
    start_point: str | None = None,
) -> str:
    """Create a local branch without checking it out. Returns the new name."""
    ensure_repo(cwd)
    branch = name.strip()
    if not branch:
        raise GitError("branch name is required", code="branch_not_found")
    if ref_exists(branch, cwd):
        raise GitError(f"branch already exists: {branch}", code="branch_exists")
    args = ["branch", branch]
    if start_point:
        start = start_point.strip()
        if not start:
            raise GitError("start point is empty", code="branch_not_found")
        if not ref_exists(start, cwd):
            raise GitError(f"start point not found: {start}", code="branch_not_found")
        args.append(start)
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git branch failed").strip()
        code = classify_git_failure(detail, kind="branch")
        raise GitError(detail, code=code if code != "generic" else "branch_failed")
    return branch


def switch_branch(
    name: str,
    cwd: Path | None = None,
    *,
    create: bool = False,
) -> str:
    """Switch to ``name`` (optionally create). Returns the branch switched to."""
    ensure_repo(cwd)
    raise_if_sequencer_busy(cwd)
    branch = name.strip()
    if not branch:
        raise GitError("branch name is required", code="branch_not_found")
    current = get_current_branch(cwd)
    if branch == current and not create:
        raise GitError(f"already on '{current}'", code="already_on_branch")
    if create:
        result = run_git("switch", "-c", branch, cwd=cwd)
    else:
        if not ref_exists(branch, cwd):
            raise GitError(f"branch not found: {branch}", code="branch_not_found")
        result = run_git("switch", branch, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git switch failed").strip()
        code = classify_git_failure(detail, kind="switch")
        raise GitError(detail, code=code if code != "generic" else "switch_failed")
    return branch


def stash_push(cwd: Path | None = None, *, message: str | None = None) -> str:
    """Stash local changes. Returns git stdout summary."""
    ensure_repo(cwd)
    if not is_worktree_dirty(cwd):
        raise GitError("No local changes to stash.", code="nothing_to_stash")
    # Include untracked files so new WIP files are covered (common CLI expectation).
    args = ["stash", "push", "-u"]
    if message:
        args.extend(["-m", message])
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git stash push failed").strip()
        code = classify_git_failure(detail, kind="stash")
        raise GitError(detail, code=code if code != "generic" else "stash_failed")
    return (result.stdout or result.stderr or "Saved working directory").strip()


def stash_pop(cwd: Path | None = None) -> str:
    """Apply and drop the latest stash entry."""
    ensure_repo(cwd)
    listed = run_git("stash", "list", cwd=cwd)
    if listed.returncode != 0:
        raise GitError(
            listed.stderr.strip() or "git stash list failed",
            code="stash_failed",
        )
    if not (listed.stdout or "").strip():
        raise GitError("No stash entries to pop.", code="nothing_to_stash")
    result = run_git("stash", "pop", cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git stash pop failed").strip()
        code = classify_git_failure(detail, kind="stash")
        # Conflicts during stash pop are common.
        if code == "pull_conflict":
            code = "merge_conflict"
        raise GitError(detail, code=code if code != "generic" else "stash_failed")
    return (result.stdout or result.stderr or "Dropped stash entry").strip()


def stash_list(cwd: Path | None = None) -> list[str]:
    ensure_repo(cwd)
    result = run_git("stash", "list", cwd=cwd)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git stash list failed", code="stash_failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
