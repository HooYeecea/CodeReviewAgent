"""Integration tests for push/pull sync checks against a local bare remote."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.common.git import (
    NothingToPull,
    NothingToPush,
    check_sync,
    is_worktree_dirty,
    pull,
    push,
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


def _commit_file(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"add {name}")


@pytest.fixture
def synced_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Local clone + bare remote already in sync (one shared commit)."""
    bare = tmp_path / "remote.git"
    local = tmp_path / "local"
    seed = tmp_path / "seed"

    _git(tmp_path, "init", "--bare", "-b", BRANCH, str(bare))
    _init_repo(seed)
    _commit_file(seed, "README.md", "hello\n")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", BRANCH)

    _git(tmp_path, "clone", str(bare), str(local))
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test User")
    return local, bare


def test_check_sync_nothing_ahead_or_behind(synced_pair: tuple[Path, Path]) -> None:
    local, _ = synced_pair
    sync = check_sync(local, do_fetch=True)
    assert sync.ahead == 0
    assert sync.behind == 0
    assert sync.remote == "origin"
    assert sync.branch == BRANCH


def test_push_raises_when_nothing_to_push(synced_pair: tuple[Path, Path]) -> None:
    local, _ = synced_pair
    with pytest.raises(NothingToPush, match="Nothing to push"):
        push(local, check=check_sync(local, do_fetch=True))


def test_pull_raises_when_nothing_to_pull(synced_pair: tuple[Path, Path]) -> None:
    local, _ = synced_pair
    with pytest.raises(NothingToPull, match="Nothing to pull"):
        pull(local, check=check_sync(local, do_fetch=True))


def test_push_succeeds_when_ahead(synced_pair: tuple[Path, Path]) -> None:
    local, bare = synced_pair
    _commit_file(local, "feature.txt", "local only\n")

    sync = check_sync(local, do_fetch=True)
    assert sync.ahead == 1
    assert sync.behind == 0

    plan = push(local, check=sync)
    assert plan.remote == "origin"
    assert plan.branch == BRANCH

    after = check_sync(local, do_fetch=True)
    assert after.ahead == 0
    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=local,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    bare_head = subprocess.run(
        ["git", "rev-parse", BRANCH],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_head == bare_head


def test_pull_succeeds_when_behind(synced_pair: tuple[Path, Path], tmp_path: Path) -> None:
    local, bare = synced_pair
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other User")
    _commit_file(other, "remote.txt", "from other\n")
    _git(other, "push", "origin", BRANCH)

    sync = check_sync(local, do_fetch=True)
    assert sync.behind == 1
    assert sync.ahead == 0

    result = pull(local, check=sync)
    assert result.behind == 1
    assert (local / "remote.txt").read_text(encoding="utf-8") == "from other\n"

    after = check_sync(local, do_fetch=True)
    assert after.behind == 0
    assert after.ahead == 0


def test_worktree_dirty_detects_uncommitted(synced_pair: tuple[Path, Path]) -> None:
    local, _ = synced_pair
    assert is_worktree_dirty(local) is False
    (local / "scratch.txt").write_text("wip\n", encoding="utf-8")
    assert is_worktree_dirty(local) is True


def test_pull_rebase_when_diverged(synced_pair: tuple[Path, Path], tmp_path: Path) -> None:
    local, bare = synced_pair
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other User")
    _commit_file(other, "remote.txt", "from other\n")
    _git(other, "push", "origin", BRANCH)
    _commit_file(local, "local.txt", "from local\n")

    sync = check_sync(local, do_fetch=True)
    assert sync.ahead == 1
    assert sync.behind == 1

    pull(local, check=sync, rebase=True)
    assert (local / "remote.txt").read_text(encoding="utf-8") == "from other\n"
    assert (local / "local.txt").read_text(encoding="utf-8") == "from local\n"
    after = check_sync(local, do_fetch=True)
    assert after.ahead == 1
    assert after.behind == 0


def _add_backup(local: Path, bare: Path, tmp_path: Path) -> Path:
    backup = tmp_path / "backup.git"
    _git(tmp_path, "clone", "--bare", str(bare), str(backup))
    _git(local, "remote", "add", "backup", str(backup))
    return backup


def test_explicit_backup_push_ignores_origin_upstream(synced_pair, tmp_path):
    local, bare = synced_pair
    _add_backup(local, bare, tmp_path)
    _commit_file(local, "new.txt", "new\n")
    _git(local, "push", "origin", BRANCH)
    sync = check_sync(local, remote="backup", for_push=True)
    assert sync.ahead == 1
    push(local, remote="backup", check=sync)
    assert check_sync(local, remote="backup", for_push=True).ahead == 0


def test_explicit_backup_pull_ignores_origin_upstream(synced_pair, tmp_path):
    local, bare = synced_pair
    backup = _add_backup(local, bare, tmp_path)
    other = tmp_path / "backup_writer"
    _git(tmp_path, "clone", str(backup), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Tester")
    _commit_file(other, "backup_only.txt", "backup\n")
    _git(other, "push", "origin", BRANCH)
    sync = check_sync(local, remote="backup")
    assert sync.behind == 1
    pull(local, remote="backup", check=sync)
    assert (local / "backup_only.txt").read_text() == "backup\n"


def test_different_upstream_branch_has_distinct_push_and_pull_targets(synced_pair, tmp_path):
    local, bare = synced_pair
    _git(local, "branch", "-m", "topic")
    other = tmp_path / "writer"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Tester")
    _commit_file(other, "incoming.txt", "incoming\n")
    _git(other, "push", "origin", BRANCH)
    sync = check_sync(local)
    assert sync.branch == "topic"
    assert sync.remote_branch == BRANCH
    assert sync.behind == 1
    pull(local, check=sync)
    assert (local / "incoming.txt").is_file()
    outgoing = check_sync(local, for_push=True)
    assert outgoing.remote_branch == "topic"
    assert outgoing.ahead > 0
    push(local, check=outgoing)
    assert check_sync(local, for_push=True).ahead == 0


def test_mismatched_remote_check_is_rejected(synced_pair, tmp_path):
    from gai.common.git import GitError

    local, bare = synced_pair
    _add_backup(local, bare, tmp_path)
    sync = check_sync(local, remote="origin")
    with pytest.raises(GitError) as caught:
        pull(local, remote="backup", check=sync)
    assert caught.value.code == "sync_target_changed"
