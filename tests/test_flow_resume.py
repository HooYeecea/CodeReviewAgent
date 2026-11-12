"""Interrupted flows using real temporary Git repositories and fake model calls."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gai.cli import run
from gai.common.llm.client import LLMError
from gai.flow import lib
from gai.flow.session import flow_lock, read_state, session_dir


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GAI_USAGE_LOG", str(tmp_path / ".gai" / "usage.jsonl"))
    monkeypatch.setenv("GAI_HISTORY_LOG", str(tmp_path / ".gai" / "commands.jsonl"))
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Tester")
    (tmp_path / ".gitignore").write_text(".gai/\n")
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("old\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("new_" + name + "\n")
    monkeypatch.setattr(lib.Confirm, "ask", lambda prompt, **k: "推送" not in prompt and "push" not in prompt.lower())
    monkeypatch.setattr(lib.Prompt, "ask", lambda *a, **k: "1")
    return tmp_path


@pytest.fixture
def model(monkeypatch):
    calls = {"plan": 0, "review": 0, "messages": 0, "stage": 0}
    def chat(self, *, system, user):
        if "split a large dirty" in system:
            calls["plan"] += 1
            return json.dumps({"summary": "two batches", "batches": [
                {"title": n, "paths": [n], "reason": "test"} for n in ("a.txt", "b.txt")
            ]})
        if "decide which local git" in system:
            calls["stage"] += 1
            return '{"paths":["a.txt","b.txt"],"reason":"test"}'
        if "Propose ONE English" in system:
            calls["messages"] += 1
            return '{"commit_message_en":"fix: update","commit_message_cn":"fix: 更新"}'
        calls["review"] += 1
        return '{"review":[],"summary":"ok","commit_message":"fix: update"}'
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    return calls, chat


def test_resume_second_batch_does_not_repeat_first_or_replan(repo, model, monkeypatch):
    calls, chat = model
    def flaky(self, **kwargs):
        if "expert code reviewer" in kwargs["system"] and calls["review"] == 1:
            calls["review"] += 1
            raise LLMError("offline", kind="network")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", flaky)
    assert run(["splitflow", "--cn"]) == 1
    data = read_state()
    assert data["batches"][0]["status"] == "committed"
    first = data["batches"][0]["commit"]
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "3"
    assert read_state()["batches"][0]["commit"] == first
    assert calls["plan"] == 1
    assert read_state()["phase"] == "push"


@pytest.mark.parametrize("kind", ["devflow", "splitflow"])
def test_commit_succeeded_before_interruption_is_reconciled(repo, model, monkeypatch, kind):
    actual = lib.git_commit
    def interrupt(*a, **k):
        actual(*a, **k)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_commit", interrupt)
    # devflow stage menu accepts the AI suggestion.
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "y" if "暂存方式" in prompt else "1")
    assert run([kind, "--cn"]) == 130
    assert read_state()["pending"]["operation"] == "commit"
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
    monkeypatch.setattr(lib, "git_commit", actual)
    assert run([kind, "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == ("2" if kind == "devflow" else "3")


def test_successful_add_before_interruption_is_reconciled(repo, model, monkeypatch):
    actual = lib.git_add
    calls = []
    def interrupt(paths):
        calls.append(paths)
        actual(paths)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_add", interrupt)
    assert run(["splitflow", "--cn"]) == 130
    assert read_state()["pending"]["operation"] == "add"
    monkeypatch.setattr(lib, "git_add", actual)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "3"
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["worktree", "index", "branch"])
def test_resume_refuses_external_changes_without_modifying_them(repo, model, monkeypatch, change):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    if change == "worktree":
        (repo / "a.txt").write_text("later edits\n")
    elif change == "index":
        git(repo, "add", "a.txt")
    else:
        git(repo, "switch", "-c", "other")
    before = git(repo, "status", "--porcelain")
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert git(repo, "status", "--porcelain") == before


def test_cached_review_survives_resume_and_model_change_invalidates_it(repo, model, monkeypatch):
    calls, _ = model
    def confirm(prompt, **kwargs):
        return "继续选择提交信息" not in prompt
    monkeypatch.setattr(lib.Confirm, "ask", confirm)
    assert run(["splitflow", "--cn"]) == 0
    assert calls["review"] == 1
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert calls["review"] == 1
    monkeypatch.setenv("GAI_MODEL", "different-model")
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert calls["review"] == 2


def test_abort_keeps_git_state_and_allows_new_flow(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    assert run(["devflow", "--cn"]) == 1
    assert run(["flow", "status", "--cn"]) == 0
    before = git(repo, "status", "--porcelain")
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: True)
    assert run(["flow", "abort", "--cn"]) == 0
    assert read_state()["phase"] == "aborted"
    assert git(repo, "status", "--porcelain") == before
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0


def test_worktree_sessions_are_separate(repo):
    first = session_dir()
    other = repo.parent / (repo.name + "_worktree")
    git(repo, "worktree", "add", "-b", "other", str(other))
    original = Path.cwd()
    try:
        os.chdir(other)
        assert session_dir() != first
    finally:
        os.chdir(original)


def test_lock_blocks_a_second_process_and_releases(repo):
    directory = session_dir()
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    code = "from pathlib import Path; from gai.flow.session import flow_lock; import sys\nwith flow_lock(Path(sys.argv[1])): pass"
    with flow_lock(directory):
        result = subprocess.run([sys.executable, "-B", "-c", code, str(directory)], env=env, capture_output=True)
        assert result.returncode != 0
        assert b"Another flow" in result.stderr
    result = subprocess.run([sys.executable, "-B", "-c", code, str(directory)], env=env, capture_output=True)
    assert result.returncode == 0


def test_corrupt_checkpoint_fails_without_git_mutation(repo):
    path = session_dir() / "current.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"unfinished":', encoding="utf-8")
    before = git(repo, "status", "--porcelain")
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert git(repo, "status", "--porcelain") == before


def test_initial_unstage_interruption_can_resume(repo, model, monkeypatch):
    git(repo, "add", "a.txt")
    actual = lib.git_unadd
    def interrupt(paths):
        actual(paths)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_unadd", interrupt)
    assert run(["splitflow", "--cn"]) == 130
    assert read_state()["pending"]["operation"] == "unadd"
    monkeypatch.setattr(lib, "git_unadd", actual)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "3"


def test_level_two_plan_survives_interrupted_second_child(repo, model, monkeypatch):
    from gai.flow.devflow import CommitBatch, CommitBatchPlan
    plans = []
    def plan(**kwargs):
        plans.append(kwargs)
        if kwargs.get("paths"):
            return CommitBatchPlan([CommitBatch(n, [n], "", commit_message="fix: " + n)
                                    for n in ("a.txt", "b.txt")], "children")
        return CommitBatchPlan([CommitBatch("parent", ["a.txt", "b.txt"], "")], "parent")
    monkeypatch.setattr(lib, "suggest_commit_batches", plan)
    monkeypatch.setattr(lib, "staged_diff_size", lambda: (200, 100, True))
    calls, chat = model
    def flaky(self, **kwargs):
        if calls["review"] == 1:
            calls["review"] += 1
            raise LLMError("offline", kind="network")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", flaky)
    assert run(["splitflow", "--cn"]) == 1
    assert [b["label"] for b in read_state()["batches"]] == ["1.1", "1.2"]
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert len(plans) == 2
    assert git(repo, "log", "-2", "--format=%s").splitlines() == ["fix: b.txt", "fix: a.txt"]


def test_failed_checkpoint_write_prevents_git_mutation(repo, model, monkeypatch):
    from gai.flow import session
    actual = session.atomic_json
    before = git(repo, "status", "--porcelain")
    def fail(path, value):
        if value.get("pending"):
            raise OSError("disk full")
        actual(path, value)
    monkeypatch.setattr(session, "atomic_json", fail)
    assert run(["splitflow", "--cn"]) == 1
    assert git(repo, "status", "--porcelain") == before
    assert read_state()["pending"] is None
    monkeypatch.setattr(session, "atomic_json", actual)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "3"


def test_added_and_deleted_files_reconcile_after_commit(repo, model, monkeypatch):
    (repo / "a.txt").unlink()
    (repo / "new.txt").write_text("new file\n")
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "." if "暂存方式" in prompt else "1")
    actual = lib.git_commit
    def interrupt(*args, **kwargs):
        actual(*args, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_commit", interrupt)
    assert run(["devflow", "--cn"]) == 130
    monkeypatch.setattr(lib, "git_commit", actual)
    assert run(["devflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
    assert git(repo, "status", "--porcelain") == ""


def test_hard_exit_and_resume_in_new_process(repo):
    # os._exit bypasses all finally blocks and simulates an abruptly killed CLI.
    code = '''
import os, sys
from pathlib import Path
Path.home = classmethod(lambda cls: Path(sys.argv[2]))
from gai.cli import run
from gai.flow import lib
from gai.common.llm.client import LLMClient
def chat(self, *, system, user):
    if "decide which local git" in system:
        return '{"paths":["a.txt","b.txt"],"reason":"test"}'
    if "Propose ONE English" in system:
        return '{"commit_message_en":"fix: update","commit_message_cn":"fix: update"}'
    return '{"review":[],"summary":"ok","commit_message":"fix: update"}'
LLMClient.chat = chat
lib.Confirm.ask = lambda prompt, **kwargs: "推送" not in prompt
lib.Prompt.ask = lambda prompt, **kwargs: "y" if "暂存方式" in prompt else "1"
if sys.argv[1] == "kill":
    commit = lib.git_commit
    def interrupted(*args, **kwargs):
        commit(*args, **kwargs)
        os._exit(77)
    lib.git_commit = interrupted
sys.exit(run(["devflow", "--cn"] + (["--resume"] if sys.argv[1] == "resume" else [])))
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    home = repo.parent / (repo.name + "_home")
    first = subprocess.run([sys.executable, "-B", "-c", code, "kill", str(home)], env=env, capture_output=True)
    assert first.returncode == 77, first.stderr.decode(errors="replace")
    second = subprocess.run([sys.executable, "-B", "-c", code, "resume", str(home)], env=env, capture_output=True)
    assert second.returncode == 0, second.stderr.decode(errors="replace")
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
    assert read_state()["phase"] == "push"
    assert read_state()["batches"][0]["status"] == "committed"


def test_successful_push_interrupted_before_checkpoint_is_not_repeated(repo, model, monkeypatch):
    from gai.flow import push as flow_push
    remote = repo.parent / (repo.name + "_remote.git")
    git(repo, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "y" if "暂存方式" in prompt else "1")
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: True)
    actual = lib._do_flow_push
    def interrupt(*args, **kwargs):
        actual(*args, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "_do_flow_push", interrupt)
    assert run(["devflow", "--cn"]) == 130
    assert read_state()["phase"] == "push"
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    calls_before = dict(model[0])
    monkeypatch.setattr(lib, "_do_flow_push", actual)
    monkeypatch.setattr(flow_push, "push_exact", lambda *a, **k: pytest.fail("must not repeat completed push"))
    assert run(["devflow", "--resume", "--cn"]) == 0
    assert read_state()["phase"] == "done"
    assert model[0] == calls_before


def test_failed_commit_reuses_review_and_selected_message(repo, model, monkeypatch):
    from gai.common.git import GitError
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "y" if "暂存方式" in prompt else "1")
    actual = lib.git_commit
    def fail(*a, **k):
        raise GitError("hook rejected commit", code="commit_failed")
    monkeypatch.setattr(lib, "git_commit", fail)
    assert run(["devflow", "--cn"]) == 1
    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    before = dict(model[0])
    monkeypatch.setattr(lib, "git_commit", actual)
    assert run(["devflow", "--resume", "--cn"]) == 0
    assert model[0] == before
    assert git(repo, "rev-list", "--count", "HEAD") == "2"


def test_devflow_transition_to_splitflow_uses_one_session(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "y" if "暂存方式" in prompt else "1")
    assert run(["devflow", "--suggest-split", "--cn"]) == 0
    assert read_state()["kind"] == "splitflow"
    assert read_state()["phase"] == "push"
    assert git(repo, "rev-list", "--count", "HEAD") == "3"
    assert run(["devflow", "--resume", "--cn"]) == 1
    assert run(["splitflow", "--resume", "--cn"]) == 0


def test_abort_can_archive_a_corrupt_checkpoint(repo, monkeypatch):
    path = session_dir() / "current.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: True)
    before = git(repo, "status", "--porcelain")
    assert run(["flow", "abort", "--cn"]) == 0
    assert not path.exists()
    assert next(path.parent.glob("corrupt-*.json")).read_text() == "{broken"
    assert git(repo, "status", "--porcelain") == before


def setup_auto_push(repo, monkeypatch):
    remote = repo.parent / (repo.name + "_auto.git")
    git(repo, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: pytest.fail("unexpected confirmation"))
    return remote


@pytest.mark.parametrize("cn,language,expected", [
    (True, "1", ["fix: update", "fix: update"]),
    (False, "2", ["fix: 更新", "fix: 更新"]),
    (True, "en,cn", ["fix: update", "fix: 更新"]),
])
def test_splitflow_yes_only_asks_language_and_pushes(repo, model, monkeypatch, cn, language, expected):
    remote = setup_auto_push(repo, monkeypatch)
    git(repo, "add", "a.txt")  # Clearing an existing index must not prompt either.
    prompts = []
    def choose(prompt, **kwargs):
        assert prompt in {"请选择", "Choose"}
        prompts.append(prompt)
        return language
    monkeypatch.setattr(lib.Prompt, "ask", choose)
    assert run(["splitflow", "-y"] + (["--cn"] if cn else [])) == 0
    assert len(prompts) == 1
    assert git(repo, "log", "-2", "--reverse", "--format=%s").splitlines() == expected
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert read_state()["phase"] == "done"
    assert read_state()["review_cn"] is cn
    assert model[0]["review"] == 2


def test_splitflow_yes_confirms_level_two_and_inherits_language(repo, model, monkeypatch):
    from gai.flow.devflow import CommitBatch, CommitBatchPlan
    setup_auto_push(repo, monkeypatch)
    prompts = []
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: prompts.append(prompt) or "2")
    def plan(**kwargs):
        if kwargs.get("paths"):
            assert kwargs["message_lang"] == "cn"
            return CommitBatchPlan([CommitBatch(n, [n], "", commit_message="fix: 更新 " + n)
                                    for n in ("a.txt", "b.txt")], "children")
        return CommitBatchPlan([CommitBatch("parent", ["a.txt", "b.txt"], "")], "parent")
    monkeypatch.setattr(lib, "suggest_commit_batches", plan)
    monkeypatch.setattr(lib, "staged_diff_size", lambda: (200, 100, True))
    assert run(["splitflow", "--yes", "--cn"]) == 0
    assert len(prompts) == 1
    assert [b["label"] for b in read_state()["batches"]] == ["1.1", "1.2"]
    assert git(repo, "log", "-2", "--reverse", "--format=%s").splitlines() == [
        "fix: 更新 a.txt", "fix: 更新 b.txt",
    ]


@pytest.mark.parametrize("failure", ["review", "message", "commit"])
def test_splitflow_yes_stops_on_failure_and_resume_keeps_mode(repo, model, monkeypatch, failure):
    from gai.common.git import GitError
    remote = setup_auto_push(repo, monkeypatch)
    monkeypatch.setattr(lib.Prompt, "ask", lambda *a, **k: "2")
    _, chat = model
    actual_commit = lib.git_commit
    def broken_chat(self, **kwargs):
        if failure == "review" and "expert code reviewer" in kwargs["system"]:
            return "invalid review"
        if failure == "message" and "Propose ONE English" in kwargs["system"]:
            return '{"commit_message_en":"fix: update"}'  # Missing selected Chinese message.
        return chat(self, **kwargs)
    def broken_commit(*a, **k):
        raise GitError("hook rejected", code="commit_failed")
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", broken_chat)
    if failure == "commit":
        monkeypatch.setattr(lib, "git_commit", broken_commit)
    assert run(["splitflow", "--yes", "--cn"]) == 1
    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert git(remote, "for-each-ref", "refs/heads") == ""
    assert read_state()["auto_confirm"] is True
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    monkeypatch.setattr(lib, "git_commit", actual_commit)
    monkeypatch.setattr(lib.Prompt, "ask", lambda *a, **k: pytest.fail("saved language must be reused"))
    # No --yes: the explicitly enabled mode is persisted in the checkpoint.
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert git(repo, "rev-list", "--count", "HEAD") == "3"
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert read_state()["phase"] == "done"


def test_resume_yes_can_enable_automation_for_an_interactive_session(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: False)
    assert run(["splitflow", "--cn"]) == 0
    assert read_state()["auto_confirm"] is False
    remote = setup_auto_push(repo, monkeypatch)
    assert run(["splitflow", "--resume", "--yes", "--cn"]) == 0
    assert read_state()["auto_confirm"] is True
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_splitflow_yes_still_rejects_changed_worktree(repo, model, monkeypatch):
    _, chat = model
    def changed_during_review(self, **kwargs):
        if "expert code reviewer" in kwargs["system"]:
            (repo / "a.txt").write_text("new external edit\n")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", changed_during_review)
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: pytest.fail("unexpected confirmation"))
    assert run(["splitflow", "--yes", "--cn"]) == 1
    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert (repo / "a.txt").read_text() == "new external edit\n"
