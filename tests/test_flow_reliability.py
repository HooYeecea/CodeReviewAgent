"""Fault injection against real local Git repositories; never contact a service."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from test_flow_resume import repo, model, git, setup_auto_push  # noqa: F401
from gai.cli import run
from gai.flow import lib
from gai.flow.session import read_state, session_dir


def test_managed_timeout_kills_descendants(tmp_path):
    from gai.common.git.process import run_managed
    marker = tmp_path / "escaped"
    child = "import time; from pathlib import Path; time.sleep(1.5); Path(%r).write_text('escaped')" % str(marker)
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(30)" % child
    with pytest.raises(subprocess.TimeoutExpired):
        run_managed([sys.executable, "-c", code], timeout=0.5)
    time.sleep(1.6)
    assert not marker.exists()


def test_abrupt_parent_exit_kills_descendants(tmp_path):
    marker, ready = tmp_path / "escaped", tmp_path / "ready"
    child = "import time; from pathlib import Path; time.sleep(1.5); Path(%r).write_text('escaped')" % str(marker)
    command = ("import subprocess,sys,time; from pathlib import Path; "
               "subprocess.Popen([sys.executable,'-c',%r]); Path(%r).touch(); time.sleep(30)") % (child, str(ready))
    driver = '''
import os, sys, threading, time
from pathlib import Path
from gai.common.git.process import run_managed
def die():
    while not Path(sys.argv[1]).exists(): time.sleep(.02)
    os._exit(77)
threading.Thread(target=die, daemon=True).start()
run_managed([sys.executable, "-c", sys.argv[2]], timeout=10)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-B", "-c", driver, str(ready), command], env=env,
                            capture_output=True, timeout=15)
    assert result.returncode == 77, result.stderr.decode(errors="replace")
    time.sleep(1.6)
    assert not marker.exists()


def test_git_timeout_is_a_recoverable_error(repo, monkeypatch):
    from gai.common.git import run_git, GitError
    monkeypatch.setenv("GAI_GIT_TIMEOUT", "0.0001")
    with pytest.raises(GitError) as error:
        run_git("add", "a.txt")
    assert error.value.code == "timeout"


def test_existing_git_lock_is_not_deleted(repo, model):
    path = repo / ".git" / "index.lock"
    path.write_text("external git")
    assert run(["splitflow", "--yes", "--cn"]) == 1
    assert path.read_text() == "external git"
    assert model[0]["plan"] == 0


def test_push_checks_push_url_instead_of_fetch_url(repo, model, monkeypatch):
    fetch_remote = setup_auto_push(repo, monkeypatch)
    push_remote = repo.parent / (repo.name + "_push.git")
    git(repo, "init", "--bare", str(push_remote))
    git(repo, "remote", "set-url", "--push", "origin", str(push_remote))
    assert run(["splitflow", "--yes", "--cn"]) == 0
    assert git(fetch_remote, "for-each-ref", "refs/heads") == ""
    assert git(push_remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_push_pins_saved_sha_even_when_branch_moves_during_push(repo, model, monkeypatch):
    from gai.flow import push
    remote = setup_auto_push(repo, monkeypatch)
    original = push.push_exact
    sent = []
    def concurrent(url, branch, head):
        sent.append(head)
        git(repo, "commit", "--allow-empty", "-m", "external commit")
        original(url, branch, head)
    monkeypatch.setattr(push, "push_exact", concurrent)
    assert run(["splitflow", "--yes", "--cn"]) == 1  # final repository verification rejects the change
    assert git(remote, "rev-parse", "main") == sent[0]
    assert git(repo, "rev-parse", "HEAD") != sent[0]


def test_checkpoint_backup_recovers_only_when_git_matches(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    path = session_dir() / "current.json"
    path.write_text("{corrupt", encoding="utf-8")
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert read_state()["recovered_backup"] is True
    assert list(path.parent.glob("corrupt-*.json"))
    path.write_text("{corrupt again", encoding="utf-8")
    (repo / "a.txt").write_text("external edit")
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert path.read_text() == "{corrupt again"  # do not overwrite until validation succeeds


def test_checkpoint_shape_errors_are_friendly(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    data = read_state()
    data.pop("checksum", None)
    data["phase"] = []
    (session_dir() / "current.json").write_text(json.dumps(data), encoding="utf-8")
    assert run(["flow", "status", "--cn"]) == 1


def test_save_failure_does_not_claim_latest_progress_saved(repo, model, monkeypatch, capsys):
    from gai.flow import session
    actual = session.atomic_json
    def fail(path, value):
        if path.name == "current.json" and value.get("pending"):
            raise OSError("disk full")
        actual(path, value)
    monkeypatch.setattr(session, "atomic_json", fail)
    assert run(["splitflow", "--yes", "--cn"]) == 1
    output = capsys.readouterr().out
    assert "Progress saved:" not in output
    assert "Checkpoint save failed" in output


def test_missing_current_does_not_silently_replace_unfinished_backup(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    current = session_dir() / "current.json"
    current.unlink()
    assert run(["splitflow", "--cn"]) == 1
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert read_state()["recovered_backup"]


def test_abort_backup_cannot_revive_discarded_flow(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: True)
    assert run(["flow", "abort", "--cn"]) == 0
    (session_dir() / "current.json").write_text("{broken", encoding="utf-8")
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert git(repo, "rev-list", "--count", "HEAD") == "1"


def test_legacy_checkpoint_upgrades_after_strict_validation(repo, model, monkeypatch):
    from gai.flow.session import observed
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    data = read_state()
    data.pop("checksum")
    data["observed"] = observed(repo, legacy=True)
    (session_dir() / "current.json").write_text(json.dumps(data), encoding="utf-8")
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert read_state()["observed"]["worktree"].startswith("v2:")


def test_push_verifies_existing_remote_history(repo, model, monkeypatch):
    remote = setup_auto_push(repo, monkeypatch)
    git(repo, "push", "origin", "HEAD:refs/heads/main")
    assert run(["splitflow", "--yes", "--cn"]) == 0
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_remote_ahead_containing_saved_commit_completes_without_push(repo, model, monkeypatch):
    from gai.flow import push
    remote = repo.parent / (repo.name + "_ahead.git")
    git(repo, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    assert run(["splitflow", "--cn"]) == 0  # pause at push
    saved = git(repo, "rev-parse", "HEAD")
    git(repo, "push", "origin", "HEAD:refs/heads/main")
    tree = git(remote, "rev-parse", "main^{tree}")
    newer = git(remote, "-c", "user.name=Remote", "-c", "user.email=remote@example.com",
                "commit-tree", tree, "-p", saved, "-m", "remote advancement")
    git(remote, "update-ref", "refs/heads/main", newer)
    monkeypatch.setattr(push, "push_exact", lambda *a: pytest.fail("already contained; do not push"))
    assert run(["splitflow", "--resume", "--yes", "--cn"]) == 0
    assert read_state()["phase"] == "done"
    assert git(remote, "rev-parse", "main") == newer
    assert git(repo, "config", "branch.main.remote") == "origin"


def test_multiple_push_urls_resume_only_missing_target(repo, model, monkeypatch):
    from gai.flow import push
    from gai.common.git import GitError
    first = setup_auto_push(repo, monkeypatch)
    second = repo.parent / (repo.name + "_second.git")
    git(repo, "init", "--bare", str(second))
    git(repo, "remote", "set-url", "--push", "origin", str(first))
    git(repo, "remote", "set-url", "--add", "--push", "origin", str(second))
    actual = push.push_exact
    calls = []
    def interrupted(url, branch, head):
        calls.append(url)
        if Path(url) == second and calls.count(url) == 1:
            raise GitError("offline", code="network")
        actual(url, branch, head)
    monkeypatch.setattr(push, "push_exact", interrupted)
    assert run(["splitflow", "--yes", "--cn"]) == 1
    assert git(first, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert sum(Path(url) == first for url in calls) == 1
    assert git(second, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
