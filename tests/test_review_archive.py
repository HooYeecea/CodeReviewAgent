"""Local review exports, without network access or changes to a real repository."""
import json
from pathlib import Path

import pytest

from test_ship_cli import staged_repo, _fake_review  # noqa: F401
from test_flow_resume import repo, model, git  # noqa: F401
from gai.cli import run
from gai.flow import lib
from gai.flow.session import read_state
from gai.review import ReviewResult, ReviewItem
from gai.review import archive


def reports(root):
    return sorted(p for p in (root / ".gai" / "reviews").glob("*/*.json") if p.name != "index.json")


def test_review_json_export_and_local_ignore(staged_repo, monkeypatch, capsys):
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    index = git(staged_repo, "write-tree")
    assert run(["review", "--save-review", "--json", "--cn"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["parsed_ok"] is True
    assert "summary.md" not in captured.out
    assert "summary.md" in captured.err
    files = reports(staged_repo)
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["snapshot"]["tree"] == index
    assert data["snapshot"]["head"] == git(staged_repo, "rev-parse", "HEAD")
    assert data["staged_files"] == ["a.txt"]
    assert data["result"]["status"] == "passed"
    assert data["commit"] is None
    assert files[0].with_suffix(".md").is_file()
    assert (files[0].parent / "summary.md").is_file()
    assert git(staged_repo, "check-ignore", str(files[0]))
    assert git(staged_repo, "write-tree") == index
    assert not (staged_repo / ".gitignore").exists()


@pytest.mark.parametrize("args", [
    ["review"], ["review", "--save-review", "--message-only"],
    ["commit", "--save-review", "--no-ai", "-m", "test", "-y"],
    ["commit", "--save-review", "--no-review", "-y"],
])
def test_no_fake_reports_when_disabled_or_no_review(staged_repo, monkeypatch, args):
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    monkeypatch.setattr("gai.commit.cmd.run_review", _fake_review)
    assert run(args) == 0
    assert not (staged_repo / ".gai" / "reviews").exists()


def test_failed_parse_is_saved_and_not_marked_passed(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.cmd.run_review", lambda **k: ReviewResult(
        parsed_ok=False, raw_text="RAW_RESPONSE_MUST_NOT_BE_STORED", summary="invalid output"))
    assert run(["review", "--save-review"]) == 1
    text = reports(staged_repo)[0].read_text(encoding="utf-8")
    assert '"status": "failed"' in text
    assert "RAW_RESPONSE_MUST_NOT_BE_STORED" not in text


def test_commit_linked_before_push(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.commit.cmd.run_review", _fake_review)
    calls = []
    def push(**kwargs):
        data = json.loads(reports(staged_repo)[0].read_text(encoding="utf-8"))
        assert data["commit"] == git(staged_repo, "rev-parse", "HEAD")
        calls.append(data["commit"])
    monkeypatch.setattr("gai.commit.cmd._do_push", push)
    assert run(["commit", "--save-review", "-y", "--push"]) == 0
    assert len(calls) == 1


def test_failed_export_prevents_commit_and_push(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.commit.cmd.run_review", _fake_review)
    head = git(staged_repo, "rev-parse", "HEAD")
    monkeypatch.setattr(archive, "atomic_text", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr("gai.commit.cmd._do_push", lambda **k: pytest.fail("must not push"))
    assert run(["commit", "--save-review", "-y", "--push"]) == 1
    assert git(staged_repo, "rev-parse", "HEAD") == head


def test_runs_from_subdirectory_and_keep_separate_runs(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    child = staged_repo / "subdir"
    child.mkdir()
    monkeypatch.chdir(child)
    for _ in range(2):
        assert run(["review", "--save-review"]) == 0
    assert len(reports(staged_repo)) == 2
    assert not (child / ".gai" / "reviews").exists()


def test_markdown_treats_model_text_as_literal(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.cmd.run_review", lambda **k: ReviewResult(
        review=[ReviewItem("warning", "[name](https://invalid.test)", 1,
                           "<script>alert(1)</script>", "**fix**")],
        truncated_diff=True, summary="[click](https://invalid.test)"))
    assert run(["review", "--save-review"]) == 0
    text = reports(staged_repo)[0].with_suffix(".md").read_text(encoding="utf-8")
    assert "<script>" not in text
    assert "\\[click\\]" in text
    assert "Truncated: True" in text


def test_splitflow_resume_repairs_partial_export_without_repeating_review(repo, model, monkeypatch):
    calls, _ = model
    original = archive.atomic_text
    def fail_markdown(path, text):
        if path.name != "summary.md" and path.suffix == ".md":
            raise OSError("disk full")
        original(path, text)
    monkeypatch.setattr(archive, "atomic_text", fail_markdown)
    head = git(repo, "rev-parse", "HEAD")
    assert run(["splitflow", "--cn", "--save-review", "--yes", "--no-push"]) == 1
    state = read_state()
    directory = state["review_archive"]["directory"]
    assert len(state["review_archive"]["records"]) == 1
    assert calls["review"] == 1
    assert git(repo, "rev-parse", "HEAD") == head
    monkeypatch.setattr(archive, "atomic_text", original)
    # Deliberately omit --save-review: the durable setting must be inherited.
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert calls["review"] == 2
    assert read_state()["review_archive"]["directory"] == directory
    assert len(reports(repo)) == 2
    for path in reports(repo):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["commit"]
        assert git(repo, "rev-parse", data["commit"] + "^{tree}") == data["snapshot"]["tree"]
        assert path.with_suffix(".md").is_file()
    manifest = json.loads((reports(repo)[0].parent / "index.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "done"
    assert manifest["completion"] == "local_only"


@pytest.mark.parametrize("mode", ["--review-current", "--replan"])
def test_re_review_retains_old_result_and_links_only_current(repo, model, monkeypatch, mode):
    _, chat = model
    def fail_messages(self, **kwargs):
        if "Propose ONE English" in kwargs["system"]:
            from gai.common.llm.client import LLMError
            raise LLMError("offline", kind="network")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail_messages)
    assert run(["splitflow", "--cn", "--save-review", "--yes", "--no-push"]) == 1
    first = reports(repo)[0]
    (repo / "a.txt").write_text("fixed\n")
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    assert run(["splitflow", "--resume", mode, "--cn"]) == 0
    assert len(reports(repo)) == 3
    assert json.loads(first.read_text(encoding="utf-8"))["commit"] is None
    assert sum(bool(json.loads(p.read_text(encoding="utf-8"))["commit"]) for p in reports(repo)) == 2


def test_devflow_interrupted_after_commit_backfills_on_resume(repo, model, monkeypatch):
    original = lib.git_commit
    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lib, "git_commit", interrupt)
    monkeypatch.setattr(lib.Prompt, "ask", lambda prompt, **k: "y" if "暂存方式" in prompt else "1")
    assert run(["devflow", "--cn", "--save-review"]) == 130
    committed = git(repo, "rev-parse", "HEAD")
    assert json.loads(reports(repo)[0].read_text(encoding="utf-8"))["commit"] is None
    monkeypatch.setattr(lib, "git_commit", original)
    assert run(["devflow", "--resume", "--cn"]) == 0
    assert len(reports(repo)) == 1
    assert json.loads(reports(repo)[0].read_text(encoding="utf-8"))["commit"] == committed
    assert model[0]["review"] == 1


def test_report_path_cannot_escape_repo(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    original = archive.new_archive
    def invalid(command):
        value = original(command)
        value["directory"] = "../../outside"
        return value
    monkeypatch.setattr(archive, "new_archive", invalid)
    assert run(["review", "--save-review"]) == 1
    assert not (staged_repo / "outside").exists()


def test_cli_exposes_save_flag_for_all_review_commands():
    from typer.main import get_command
    from gai.cli import app
    commands = get_command(app).commands
    for name in ("review", "commit", "splitflow", "devflow"):
        assert any("--save-review" in p.opts for p in commands[name].params)


def test_switch_to_splitflow_keeps_collection(repo, model, monkeypatch):
    from dataclasses import replace
    from gai.review.engine import load_staged_diff_info
    git(repo, "add", "a.txt", "b.txt")
    monkeypatch.setattr("gai.review.cmd.load_staged_diff_info",
                        lambda: replace(load_staged_diff_info(), exceeds=True, limit=1))
    assert run(["review", "--cn", "--save-review"]) == 0
    assert len(reports(repo)) == 2
    for path in reports(repo):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["command"] == "review"
        assert data["flow_kind"] == "splitflow"


def test_existing_tracked_reports_are_not_overwritten(staged_repo, monkeypatch):
    path = staged_repo / ".gai" / "reviews" / "existing.md"
    path.parent.mkdir(parents=True)
    path.write_text("keep this report")
    git(staged_repo, "add", str(path))
    index = git(staged_repo, "write-tree")
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    assert run(["review", "--save-review"]) == 1
    assert path.read_text() == "keep this report"
    assert git(staged_repo, "write-tree") == index


def test_ignore_negation_stops_export(staged_repo, monkeypatch):
    (staged_repo / ".gitignore").write_text("!.gai/reviews/\n!.gai/reviews/**\n")
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    assert run(["review", "--save-review"]) == 1
    assert not reports(staged_repo)


def test_no_sensitive_request_or_source_content_in_report(staged_repo, monkeypatch):
    monkeypatch.setenv("GAI_API_KEY", "sensitive-test-key")
    monkeypatch.setenv("GAI_BASE_URL", "https://sensitive-endpoint.invalid")
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    assert run(["review", "--save-review"]) == 0
    for path in reports(staged_repo)[0].parent.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "sensitive-test-key" not in text
        assert "sensitive-endpoint" not in text
        assert "hello world" not in text  # staged file contents


def test_abort_updates_saved_summary(repo, model, monkeypatch):
    _, chat = model
    def fail_message(self, **kwargs):
        if "Propose ONE English" in kwargs["system"]:
            from gai.common.llm.client import LLMError
            raise LLMError("stop before commit")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail_message)
    assert run(["splitflow", "--cn", "--save-review", "--yes", "--no-push"]) == 1
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: True)
    assert run(["flow", "abort", "--cn"]) == 0
    data = json.loads((reports(repo)[0].parent / "index.json").read_text(encoding="utf-8"))
    assert data["phase"] == "aborted"


def test_final_summary_failure_keeps_flow_resumable(repo, model, monkeypatch):
    original = archive.atomic_text
    def fail_final_summary(path, text):
        if path.name == "index.json" and '"phase": "done"' in text:
            raise OSError("disk full at completion")
        original(path, text)
    monkeypatch.setattr(archive, "atomic_text", fail_final_summary)
    assert run(["splitflow", "--cn", "--save-review", "--yes", "--no-push"]) == 1
    assert read_state()["phase"] == "push"
    head = git(repo, "rev-parse", "HEAD")
    calls = dict(model[0])
    monkeypatch.setattr(archive, "atomic_text", original)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    assert read_state()["phase"] == "done"
    assert git(repo, "rev-parse", "HEAD") == head
    assert model[0] == calls


def test_enable_collection_on_resume_reuses_cached_review(repo, model, monkeypatch):
    _, chat = model
    def fail_message(self, **kwargs):
        if "Propose ONE English" in kwargs["system"]:
            from gai.common.llm.client import LLMError
            raise LLMError("offline")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail_message)
    assert run(["splitflow", "--cn", "--yes", "--no-push"]) == 1
    assert not reports(repo)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    assert run(["splitflow", "--resume", "--save-review", "--cn"]) == 0
    assert len(reports(repo)) == 2
    assert model[0]["review"] == 2
