"""Integration tests for push/pull sync checks against a local bare remote."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.git_ops import (
    NothingToPull,
    NothingToPush,
    check_sync,
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
