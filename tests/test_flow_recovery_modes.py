"""Recovery controls and strict/incremental state checks using real Git."""
from pathlib import Path

import pytest

from test_flow_resume import repo, model, git  # noqa: F401
from gai.cli import run
from gai.flow import lib
from gai.flow.session import read_state, session_dir
from gai.common.llm.client import LLMError


def test_no_push_finishes_without_remote_or_push_confirmation(repo, model, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: pytest.fail("unexpected confirmation"))
    assert run(["splitflow", "--cn", "--yes", "--no-push"]) == 0
    assert read_state()["phase"] == "done"
    assert read_state()["completion"] == "local_only"
    assert git(repo, "rev-list", "--count", "HEAD") == "3"


def test_interactive_resume_disables_saved_automatic_mode(repo, model, monkeypatch):
    _, chat = model
    def fail(self, **kwargs):
        if "expert code reviewer" in kwargs["system"]:
            raise LLMError("offline", kind="network")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail)
    assert run(["splitflow", "--cn", "--yes", "--no-push"]) == 1
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    prompts = []
    monkeypatch.setattr(lib.Confirm, "ask", lambda prompt, **k: prompts.append(prompt) or False)
    monkeypatch.setattr(lib.Prompt, "ask", lambda *a, **k: pytest.fail("language already saved"))
    assert run(["splitflow", "--cn", "--resume", "--interactive"]) == 0
    assert read_state()["auto_confirm"] is False
    assert any("继续选择提交信息" in p for p in prompts)
    assert git(repo, "rev-list", "--count", "HEAD") == "1"


def pause_after_review(repo, monkeypatch):
    monkeypatch.setattr(lib.Confirm, "ask", lambda prompt, **k: "继续选择提交信息" not in prompt)
    assert run(["splitflow", "--cn"]) == 0
    assert read_state()["batches"][0]["review"]


def test_review_current_restages_fix_and_invalidates_cached_review(repo, model, monkeypatch):
    pause_after_review(repo, monkeypatch)
    (repo / "a.txt").write_text("fixed after review\n")
    assert run(["splitflow", "--cn", "--resume"]) == 1
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: pytest.fail("automatic recovery"))
    assert run(["splitflow", "--cn", "--resume", "--review-current", "--yes", "--no-push"]) == 0
    assert git(repo, "show", "HEAD~1:a.txt") == "fixed after review"
    assert model[0]["plan"] == 1
    assert model[0]["review"] == 3
    assert read_state()["completion"] == "local_only"


def test_review_current_rejects_changes_outside_batch(repo, model, monkeypatch):
    pause_after_review(repo, monkeypatch)
    (repo / "b.txt").write_text("unrelated edit\n")
    before = git(repo, "write-tree")
    assert run(["splitflow", "--cn", "--resume", "--review-current", "--yes"]) == 1
    assert git(repo, "write-tree") == before
    assert git(repo, "rev-list", "--count", "HEAD") == "1"


def test_replan_keeps_completed_commit_and_plans_only_remaining_changes(repo, model, monkeypatch):
    from gai.flow.devflow import CommitBatch, CommitBatchPlan
    calls, chat = model
    def fail_second(self, **kwargs):
        if "expert code reviewer" in kwargs["system"] and calls["review"] == 1:
            raise LLMError("offline", kind="network")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail_second)
    assert run(["splitflow", "--cn", "--yes", "--no-push"]) == 1
    committed = read_state()["batches"][0]["commit"]
    (repo / "b.txt").write_text("fixed b\n")
    (repo / "c.txt").write_text("new change\n")
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    monkeypatch.setattr(lib, "suggest_commit_batches", lambda **k: CommitBatchPlan(
        [CommitBatch(n, [n], "remaining") for n in ("b.txt", "c.txt")], "new plan"))
    assert run(["splitflow", "--cn", "--resume", "--replan"]) == 0
    data = read_state()
    assert data["completed_batches"][0]["commit"] == committed
    assert git(repo, "rev-parse", "HEAD~2") == committed
    assert [b["batch"]["paths"] for b in data["batches"]] == [["b.txt"], ["c.txt"]]
    assert git(repo, "rev-list", "--count", "HEAD") == "4"
    assert data["phase"] == "done"


def test_preflight_reports_files_without_updating_checkpoint_or_index(repo, model, monkeypatch, capsys):
    pause_after_review(repo, monkeypatch)
    checkpoint = session_dir() / "current.json"
    before = checkpoint.read_bytes()
    tree = git(repo, "write-tree")
    assert run(["flow", "status", "--check", "--cn"]) == 0
    assert checkpoint.read_bytes() == before
    (repo / "a.txt").write_text("new edit\n")
    assert run(["flow", "status", "--check", "--cn"]) == 1
    assert "a.txt" in capsys.readouterr().err
    assert checkpoint.read_bytes() == before
    assert git(repo, "write-tree") == tree


def test_preflight_can_recognize_completed_pending_commit_without_saving(repo, model, monkeypatch):
    actual = lib.git_commit
    def interrupt(*a, **k):
        actual(*a, **k)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_commit", interrupt)
    assert run(["splitflow", "--yes", "--cn", "--no-push"]) == 130
    path = session_dir() / "current.json"
    before = path.read_bytes()
    assert run(["flow", "status", "--check", "--cn"]) == 0
    assert path.read_bytes() == before
    assert read_state()["pending"]["operation"] == "commit"


@pytest.mark.parametrize("args", [["--yes", "--interactive"], ["--replan"], ["--review-current"]])
def test_invalid_recovery_flags_do_not_create_a_session(repo, args):
    assert run(["splitflow", "--cn", *args]) == 1
    assert read_state() is None


def test_file_hash_reuse_is_process_local_and_strict_reads_bypass_it(repo, monkeypatch):
    from gai.flow.fingerprint import file_manifest
    cache = {}
    reads = []
    actual = Path.open
    def tracked(path, *args, **kwargs):
        if args and args[0] == "rb" and path.parent == repo:
            reads.append(path.name)
        return actual(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", tracked)
    first = file_manifest(repo, cache=cache)
    count = len(reads)
    assert count >= 3
    assert file_manifest(repo, cache=cache, strict=False) == first
    assert len(reads) == count
    (repo / "a.txt").write_text("changed\n")
    second = file_manifest(repo, cache=cache, strict=False)
    assert len(reads) == count + 1
    assert second["a.txt"] != first["a.txt"]
    file_manifest(repo, cache=cache, strict=True)
    assert len(reads) >= count * 2 + 1
