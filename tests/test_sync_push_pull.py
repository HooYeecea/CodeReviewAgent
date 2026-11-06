"""Integration tests for push/pull sync checks against a local bare remote."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.common.git import (
    GitError,
    NothingToPull,
    NothingToPush,
    check_sync,
    is_worktree_dirty,
    pull,
    push,
    plan_push,
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


def _value(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_push_ignores_configured_destination_mapping(synced_pair):
    local, bare = synced_pair
    original = _value(bare, "rev-parse", BRANCH)
    _git(local, "config", "remote.origin.push", "refs/heads/main:refs/heads/release")
    _git(local, "config", "push.followTags", "true")
    _commit_file(local, "feature.txt", "new\n")
    _git(local, "tag", "-a", "private-tag", "-m", "stay local")
    plan = push(local)
    assert plan.head == _value(bare, "rev-parse", BRANCH)
    assert plan.head != original
    assert _value(bare, "for-each-ref", "--format=%(refname)") == "refs/heads/main"


@pytest.mark.parametrize("change", ["head", "branch", "url"])
def test_push_rejects_changes_after_check(synced_pair, tmp_path, change):
    local, bare = synced_pair
    original = _value(bare, "rev-parse", BRANCH)
    _commit_file(local, "feature.txt", "new\n")
    sync = check_sync(local, for_push=True)
    if change == "head":
        _commit_file(local, "later.txt", "not confirmed\n")
    elif change == "branch":
        _git(local, "switch", "-c", "other")
    else:
        backup = _add_backup(local, bare, tmp_path)
        _git(local, "remote", "set-url", "--push", "origin", str(backup))
    with pytest.raises(GitError) as error:
        push(local, check=sync)
    assert error.value.code == "sync_target_changed"
    assert _value(bare, "rev-parse", BRANCH) == original


def test_push_pins_sha_when_head_moves_during_execution(synced_pair, monkeypatch):
    from gai.common.git import remote as impl
    local, bare = synced_pair
    _commit_file(local, "checked.txt", "checked\n")
    sync = check_sync(local, for_push=True)
    actual = impl.run_git
    def concurrent(*args, **kwargs):
        if args[0] == "push":
            _commit_file(local, "later.txt", "unconfirmed\n")
        return actual(*args, **kwargs)
    monkeypatch.setattr(impl, "run_git", concurrent)
    with pytest.raises(GitError) as error:
        push(local, check=sync)
    assert error.value.code == "sync_target_changed"
    assert _value(bare, "rev-parse", BRANCH) == sync.push_plan.head
    assert _value(local, "rev-parse", "HEAD") != sync.push_plan.head


@pytest.mark.parametrize("multiple", [False, True])
def test_push_checks_actual_push_urls(synced_pair, tmp_path, multiple):
    local, bare = synced_pair
    backup = _add_backup(local, bare, tmp_path)
    _commit_file(local, "new.txt", "new\n")
    _git(local, "push", "origin", BRANCH)  # fetch URL is already up to date
    _git(local, "remote", "set-url", "--push", "origin", str(backup))
    if multiple:
        _git(local, "remote", "set-url", "--add", "--push", "origin", str(bare))
    sync = check_sync(local, for_push=True)
    assert sync.ahead == 1
    push(local, check=sync)
    assert _value(backup, "rev-parse", BRANCH) == _value(local, "rev-parse", "HEAD")
    assert check_sync(local, for_push=True).ahead == 0
    assert _value(local, "for-each-ref", "refs/gai/push-check") == ""


def test_push_verifies_remote_after_reported_success(synced_pair, monkeypatch):
    from gai.common.git import remote as impl, GitResult
    local, _ = synced_pair
    _commit_file(local, "new.txt", "new\n")
    actual = impl.run_git
    def no_write(*args, **kwargs):
        return GitResult("", "", 0) if args[0] == "push" else actual(*args, **kwargs)
    monkeypatch.setattr(impl, "run_git", no_write)
    with pytest.raises(GitError, match="does not contain"):
        push(local)


def test_first_push_sets_upstream_without_refspec_mapping(tmp_path):
    local, bare = tmp_path / "local", tmp_path / "remote.git"
    _init_repo(local)
    _git(tmp_path, "init", "--bare", str(bare))
    _commit_file(local, "new.txt", "new\n")
    _git(local, "remote", "add", "origin", str(bare))
    _git(local, "config", "remote.origin.push", "refs/heads/main:refs/heads/release")
    plan = plan_push(local)
    push(local, check=check_sync(local, for_push=True, push_plan=plan))
    assert _value(bare, "rev-parse", BRANCH) == plan.head
    assert _value(local, "config", "branch.main.remote") == "origin"
    assert _value(local, "config", "branch.main.merge") == "refs/heads/main"
    assert _value(local, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"


def test_push_checks_all_destinations_before_writing(synced_pair, tmp_path):
    local, bare = synced_pair
    original = _value(bare, "rev-parse", BRANCH)
    backup = _add_backup(local, bare, tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(backup), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Tester")
    _commit_file(other, "remote.txt", "remote\n")
    _git(other, "push", "origin", BRANCH)
    _commit_file(local, "local.txt", "local\n")
    _git(local, "remote", "set-url", "--push", "origin", str(bare))
    _git(local, "remote", "set-url", "--add", "--push", "origin", str(backup))
    with pytest.raises(GitError) as error:
        push(local)
    assert error.value.code == "rejected"
    assert _value(bare, "rev-parse", BRANCH) == original


def test_cli_push_keeps_plan_from_before_confirmation(synced_pair, monkeypatch):
    from gai.sync import push_pull
    local, bare = synced_pair
    monkeypatch.chdir(local)
    original = _value(bare, "rev-parse", BRANCH)
    _commit_file(local, "checked.txt", "checked\n")
    def confirm(*args, **kwargs):
        _commit_file(local, "later.txt", "unconfirmed\n")
        return True
    monkeypatch.setattr(push_pull.Confirm, "ask", confirm)
    with pytest.raises(GitError) as error:
        push_pull._do_push()
    assert error.value.code == "sync_target_changed"
    assert _value(bare, "rev-parse", BRANCH) == original


@pytest.mark.parametrize("rebase_config", ["pull.rebase", "branch.main.rebase"])
def test_merge_pull_preserves_local_commits_despite_rebase_config(synced_pair, tmp_path, rebase_config):
    local, bare = synced_pair
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "Tester")
    _commit_file(other, "remote.txt", "remote\n")
    _git(other, "push", "origin", BRANCH)
    remote_head = _value(bare, "rev-parse", BRANCH)
    _commit_file(local, "local.txt", "local\n")
    local_head = _value(local, "rev-parse", "HEAD")
    _git(local, "config", rebase_config, "true")
    _git(local, "config", "pull.ff", "only")
    pull(local, rebase=False)
    assert _value(local, "show", "-s", "--format=%P", "HEAD").split() == [local_head, remote_head]
