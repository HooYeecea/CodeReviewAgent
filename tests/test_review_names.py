"""Readable names, stable identities, and compatibility with older checkpoints."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from urllib.parse import unquote

import pytest

from test_ship_cli import staged_repo  # noqa: F401
from test_flow_resume import repo, model, git  # noqa: F401
from test_review_archive import reports
from gai.cli import run
from gai.flow.session import read_state, session_dir, write_checkpoint
from gai.review import ReviewResult
from gai.review import archive
from gai.review.names import safe_name, valid_component, review_title, report_stem


@pytest.mark.parametrize("value", [
    '../危险/路径\\目标:日志*?"<>|', 'CON', 'con.txt', 'NUL', 'COM¹', 'LPT9.log',
    '... ', '\x00\x01\x1f', '含\u202e双向字符', '标题' * 100, '😀' * 100,
])
def test_windows_safe_names(value):
    name = safe_name(value)
    assert valid_component(name)
    assert len(name.encode("utf-16-le")) <= 72
    assert not re.search(r'[<>:"/\\|?*]', name)
    assert name not in {".", "..", ""}


@pytest.mark.parametrize("name", ['../bad', 'a/b', 'a\\b', 'NUL.txt', 'bad.', 'bad ', '.', '..', 'x\x00', ''])
def test_reject_unsafe_saved_components(name):
    assert not valid_component(name)


def sample_record():
    return {"id": "a" * 32, "language": "cn", "staged_files": ["src/archive.py"],
            "snapshot": {}, "result": {"parsed_ok": True, "summary": "改进报告保存。修复多个问题。"}}


def test_titles_prefer_batch_then_summary_then_paths():
    record = sample_record()
    assert review_title(record, "恢复与提交关联") == "恢复与提交关联"
    assert review_title(record) == "改进报告保存"
    assert review_title(record, "devflow") == "改进报告保存"
    record["result"]["summary"] = "## 摘要\n修复路径错误。细节在下文。"
    assert review_title(record) == "修复路径错误"
    record["result"]["summary"] = "looks fine"
    assert review_title(record) == "archive.py"
    record["result"]["parsed_ok"] = False
    record["result"]["summary"] = "RAW_FAILED_RESPONSE"
    assert review_title(record) == "archive.py"


def test_concurrent_same_topic_reserves_distinct_directories(tmp_path, monkeypatch):
    folder = tmp_path / ".gai" / "reviews"
    folder.mkdir(parents=True)
    def create(_):
        collector = archive.ReviewCollection("review", True)
        collector.root = tmp_path
        collector.archive["directory"] = "20261102-153020_" + collector.archive["id"]
        collector.prepare_parent = lambda: folder
        record = sample_record()
        collector.name_record(record)
        return collector.archive, record
    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(create, range(8)))
    directories = [a["directory"] for a, _ in outputs]
    assert len(set(directories)) == 8
    assert "20261102-153020_改进报告保存" in directories
    for value, record in outputs:
        assert value["id"] not in value["directory"]
        assert (folder / value["directory"] / ".archive-id").read_text() == value["id"]
        assert record["filename"] == "01_改进报告保存"


def test_repeated_scope_names_and_existing_file_collision(tmp_path):
    collector = archive.ReviewCollection("review", True)
    collector.root = tmp_path
    collector.archive["directory"] = "20261102-153020_改进报告保存"
    collector.archive["directory_named"] = True
    folder = tmp_path / ".gai" / "reviews" / collector.archive["directory"]
    folder.mkdir(parents=True)
    unrelated = folder / "01_改进报告保存.md"
    unrelated.write_text("keep")
    first = sample_record()
    collector.name_record(first)
    assert first["filename"] == "01_改进报告保存_2"
    collector.archive["records"].append(first)
    second = sample_record()
    second["id"] = "b" * 32
    collector.name_record(second)
    assert second["filename"] == "02_改进报告保存_第2次审查"
    assert unrelated.read_text() == "keep"


def test_report_metadata_and_encoded_links(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.cmd.run_review", lambda **k: ReviewResult(
        summary="修复 [缓存] (#2) 100% 的问题。更详细的解释。"))
    assert run(["review", "--save-review", "--cn"]) == 0
    path = reports(staged_repo)[0]
    record = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((path.parent / "index.json").read_text(encoding="utf-8"))
    assert path.stem == record["filename"]
    assert record["id"] not in path.name
    assert manifest["id"] not in path.parent.name
    assert "修复" in path.name and "修复" in path.parent.name
    assert record["id"] in path.with_suffix(".md").read_text(encoding="utf-8")
    summary = (path.parent / "summary.md").read_text(encoding="utf-8")
    links = re.findall(r'\]\(([^\s)]+\.md)\)', summary)
    assert len(links) == 1
    assert (path.parent / unquote(links[0])).is_file()
    assert "%23" in links[0] and "%25" in links[0]


def pause_at_message(model, monkeypatch):
    _, chat = model
    def fail(self, **kwargs):
        if "Propose ONE English" in kwargs["system"]:
            from gai.common.llm.client import LLMError
            raise LLMError("pause before commit")
        return chat(self, **kwargs)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", fail)
    assert run(["splitflow", "--save-review", "--cn", "--yes", "--no-push"]) == 1
    return chat


def test_resume_keeps_names_and_ids_when_linking_commit(repo, model, monkeypatch):
    chat = pause_at_message(model, monkeypatch)
    before = reports(repo)[0]
    record = json.loads(before.read_text(encoding="utf-8"))
    assert before.stem == "01_a.txt"  # batch title wins over generic model summary
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    after = json.loads(before.read_text(encoding="utf-8"))
    assert after["id"] == record["id"]
    assert after["filename"] == record["filename"]
    assert after["commit"]
    assert len({p.parent for p in reports(repo)}) == 1


def test_legacy_checkpoint_keeps_old_directory_and_filenames(repo, model, monkeypatch):
    chat = pause_at_message(model, monkeypatch)
    state = read_state()
    saved = state["review_archive"]
    # Simulate a genuine v1 checkpoint plus its existing report files.
    old_folder = repo / ".gai" / "reviews" / saved["directory"]
    legacy_name = "20261030-120000_" + saved["id"]
    legacy_folder = old_folder.with_name(legacy_name)
    old_folder.rename(legacy_folder)
    (legacy_folder / ".archive-id").unlink()
    for item in saved["records"]:
        previous = item.pop("filename")
        item.pop("title", None)
        item.pop("review_number", None)
        for suffix in (".md", ".json"):
            (legacy_folder / (previous + suffix)).rename(legacy_folder / (report_stem(item) + suffix))
    saved["directory"] = legacy_name
    for key in ("id", "naming_version", "directory_named"):
        saved.pop(key)
    write_checkpoint(session_dir(), state)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    assert run(["splitflow", "--resume", "--cn"]) == 0
    first = saved["records"][0]
    old_file = legacy_folder / (report_stem(first) + ".json")
    assert old_file.is_file()
    assert json.loads(old_file.read_text(encoding="utf-8"))["commit"]
    assert read_state()["review_archive"]["directory"] == legacy_name
    assert len(list((repo / ".gai" / "reviews").iterdir())) == 1


def test_other_run_owner_is_not_overwritten(repo, model, monkeypatch):
    chat = pause_at_message(model, monkeypatch)
    path = reports(repo)[0]
    before = path.read_bytes()
    (path.parent / ".archive-id").write_text("other-run")
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    head = git(repo, "rev-parse", "HEAD")
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert path.read_bytes() == before


@pytest.mark.parametrize("filename", ["../outside", "SUMMARY", "index", "NUL.txt"])
def test_checkpoint_rejects_unsafe_or_reserved_report_names(filename):
    value = archive.new_archive("review")
    record = sample_record()
    record["filename"] = filename
    value["records"] = [record]
    with pytest.raises(ValueError):
        archive.validate_archive(value)


def test_checkpoint_rejects_case_insensitive_duplicate_names():
    value = archive.new_archive("review")
    first = sample_record()
    second = copy.deepcopy(first)
    second["id"] = "b" * 32
    first["filename"], second["filename"] = "01_Title", "01_title"
    value["records"] = [first, second]
    with pytest.raises(ValueError):
        archive.validate_archive(value)
