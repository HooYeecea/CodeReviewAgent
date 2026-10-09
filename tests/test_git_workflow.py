"""Tests for gai merge / rebase / switch / stash wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.git_ops import (
    GitError,
    commits_ahead_of_head,
    create_branch,
    get_current_branch,
    is_worktree_dirty,
    list_local_branches,
    merge,
    merge_abort,
    merge_continue,
    merge_in_progress,
    rebase,
    rebase_abort,
    rebase_continue,
    rebase_in_progress,
    stash_list,
    stash_pop,
    stash_push,
    switch_branch,
)

BRANCH = "main"


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise AssertionError(f"git {' '.join(args)} failed: {detail}")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", BRANCH)
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")


def _commit_file(repo: Path, name: str, content: str, msg: str | None = None) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", msg or f"add {name}")


@pytest.fixture
def branched_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "README.md", "base\n")
    _git(repo, "switch", "-c", "feature")
    _commit_file(repo, "feature.txt", "feat\n")
    _git(repo, "switch", BRANCH)
    return repo


def test_merge_brings_feature_commits(branched_repo: Path) -> None:
    repo = branched_repo
    assert commits_ahead_of_head("feature", repo) == 1
    brought = merge("feature", repo)
    assert brought == 1
    assert (repo / "feature.txt").is_file()


def test_merge_nothing_when_up_to_date(branched_repo: Path) -> None:
    repo = branched_repo
    merge("feature", repo)
    with pytest.raises(GitError) as caught:
        merge("feature", repo)
    assert caught.value.code == "nothing_to_merge"


def test_merge_conflict(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "conflict.txt", "main side\n", msg="main conflict")
    _git(repo, "switch", "feature")
    _commit_file(repo, "conflict.txt", "feature side\n", msg="feature conflict")
    _git(repo, "switch", BRANCH)
    with pytest.raises(GitError) as caught:
        merge("feature", repo)
    assert caught.value.code == "merge_conflict"
    assert merge_in_progress(repo)
    merge_abort(repo)
    assert not merge_in_progress(repo)


def test_rebase_onto_main(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "main2.txt", "m2\n", msg="main2")
    _git(repo, "switch", "feature")
    replayed = rebase(BRANCH, repo)
    assert replayed >= 1
    assert get_current_branch(repo) == "feature"


def test_create_branch_without_checkout(branched_repo: Path) -> None:
    repo = branched_repo
    before = get_current_branch(repo)
    created = create_branch("topic", repo)
    assert created == "topic"
    assert get_current_branch(repo) == before
    assert "topic" in list_local_branches(repo)
    with pytest.raises(GitError) as caught:
        create_branch("topic", repo)
    assert caught.value.code == "branch_exists"


def test_create_branch_from_start_point(branched_repo: Path) -> None:
    repo = branched_repo
    before = get_current_branch(repo)
    create_branch("from-feature", repo, start_point="feature")
    assert get_current_branch(repo) == before
    assert "from-feature" in list_local_branches(repo)


def test_switch_and_create(branched_repo: Path) -> None:
    repo = branched_repo
    landed = switch_branch("feature", repo)
    assert landed == "feature"
    assert get_current_branch(repo) == "feature"
    created = switch_branch("topic", repo, create=True)
    assert created == "topic"
    assert get_current_branch(repo) == "topic"


def test_switch_missing_branch(branched_repo: Path) -> None:
    with pytest.raises(GitError) as caught:
        switch_branch("nope", branched_repo)
    assert caught.value.code == "branch_not_found"


def test_stash_push_and_pop(branched_repo: Path) -> None:
    repo = branched_repo
    (repo / "wip.txt").write_text("draft\n", encoding="utf-8")
    assert is_worktree_dirty(repo)
    stash_push(repo, message="wip")
    assert not is_worktree_dirty(repo)
    assert stash_list(repo)
    stash_pop(repo)
    assert (repo / "wip.txt").is_file()


def test_stash_nothing(branched_repo: Path) -> None:
    with pytest.raises(GitError) as caught:
        stash_push(branched_repo)
    assert caught.value.code == "nothing_to_stash"


def test_merge_continue_after_resolve(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "conflict.txt", "main side\n", msg="main conflict")
    _git(repo, "switch", "feature")
    _commit_file(repo, "conflict.txt", "feature side\n", msg="feature conflict")
    _git(repo, "switch", BRANCH)
    with pytest.raises(GitError) as caught:
        merge("feature", repo)
    assert caught.value.code == "merge_conflict"
    (repo / "conflict.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    merge_continue(repo)
    assert not merge_in_progress(repo)
    assert (repo / "conflict.txt").read_text(encoding="utf-8") == "resolved\n"


def test_merge_busy_blocks_new_merge(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "conflict.txt", "main side\n", msg="main conflict")
    _git(repo, "switch", "feature")
    _commit_file(repo, "conflict.txt", "feature side\n", msg="feature conflict")
    _git(repo, "switch", BRANCH)
    with pytest.raises(GitError):
        merge("feature", repo)
    with pytest.raises(GitError) as caught:
        merge("feature", repo)
    assert caught.value.code == "merge_in_progress"
    merge_abort(repo)


def test_merge_abort_when_idle(branched_repo: Path) -> None:
    with pytest.raises(GitError) as caught:
        merge_abort(branched_repo)
    assert caught.value.code == "no_merge_in_progress"


def test_rebase_continue_and_abort(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "conflict.txt", "main side\n", msg="main conflict")
    _git(repo, "switch", "feature")
    _commit_file(repo, "conflict.txt", "feature side\n", msg="feature conflict")
    with pytest.raises(GitError) as caught:
        rebase(BRANCH, repo)
    assert caught.value.code == "rebase_conflict"
    assert rebase_in_progress(repo)
    rebase_abort(repo)
    assert not rebase_in_progress(repo)

    with pytest.raises(GitError):
        rebase(BRANCH, repo)
    (repo / "conflict.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "conflict.txt")
    rebase_continue(repo)
    assert not rebase_in_progress(repo)


def test_cli_merge_continue_abort_flags(branched_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gai.cli import run

    repo = branched_repo
    _commit_file(repo, "conflict.txt", "main side\n", msg="main conflict")
    _git(repo, "switch", "feature")
    _commit_file(repo, "conflict.txt", "feature side\n", msg="feature conflict")
    _git(repo, "switch", BRANCH)
    with pytest.raises(GitError):
        merge("feature", repo)

    monkeypatch.chdir(repo)
    monkeypatch.setattr("gai.commands.sync.Confirm.ask", lambda *a, **k: True)

    code = run(["merge", "--abort", "--cn"])
    assert code == 0
    assert not merge_in_progress(repo)

    code = run(["merge", "--continue"])
    assert code == 0

    code = run(["merge", "--continue", "--abort"])
    assert code == 2
