"""Tests for gai merge / rebase / switch / stash wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.git_ops import (
    GitError,
    commits_ahead_of_head,
    get_current_branch,
    is_worktree_dirty,
    merge,
    rebase,
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
    # Abort so the fixture cleanup stays clean.
    _git(repo, "merge", "--abort")


def test_rebase_onto_main(branched_repo: Path) -> None:
    repo = branched_repo
    _commit_file(repo, "main2.txt", "m2\n", msg="main2")
    _git(repo, "switch", "feature")
    replayed = rebase(BRANCH, repo)
    assert replayed >= 1
    assert get_current_branch(repo) == "feature"


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
