"""Tests for gai devflow helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from gai.commands.ship import parse_batch_message_lang_spec
from gai.devflow import (
    CommitBatch,
    fallback_commit_batches,
    normalize_commit_batches,
    normalize_path_input,
    parse_bilingual_messages,
    parse_commit_batch_plan,
    parse_stage_suggestion,
    stageable_paths_summary,
)
from gai.git_ops import list_change_entries


def test_parse_stage_suggestion() -> None:
    text = """
    {
      "paths": ["src/gai/cli.py", "README.md"],
      "reason": "Keep docs with the CLI change"
    }
    """
    sug = parse_stage_suggestion(text)
    assert sug.parsed_ok
    assert sug.paths == ["src/gai/cli.py", "README.md"]
    assert sug.reason


def test_parse_bilingual_messages() -> None:
    text = """
    {
      "commit_message_en": "feat(cli): add devflow command",
      "commit_message_cn": "feat(cli): 新增 devflow 引导流程"
    }
    """
    msg = parse_bilingual_messages(text)
    assert msg.parsed_ok
    assert msg.message_en.startswith("feat(cli):")
    assert "devflow" in msg.message_cn


def test_normalize_path_input() -> None:
    assert normalize_path_input("a.py, b.py  c.py") == ["a.py", "b.py", "c.py"]
    assert normalize_path_input(".") == ["."]


def test_parse_commit_batch_plan() -> None:
    text = """
    {
      "summary": "Split CLI refactor from docs",
      "batches": [
        {
          "title": "CLI modules",
          "paths": ["src/gai/cli.py", "src/gai/commands/ship.py"],
          "reason": "Core command split",
          "commit_message_en": "refactor(cli): split commands",
          "commit_message_cn": "refactor(cli): 拆分命令模块"
        },
        {
          "title": "Docs",
          "paths": ["README.md"],
          "reason": "Docs follow the split"
        }
      ]
    }
    """
    plan = parse_commit_batch_plan(text)
    assert plan.parsed_ok
    assert len(plan.batches) == 2
    assert plan.batches[0].paths[0] == "src/gai/cli.py"
    assert plan.batches[0].message_hint_en.startswith("refactor(cli):")


def test_normalize_commit_batches_dedupes_and_appends_leftover() -> None:
    batches = [
        CommitBatch(title="a", paths=["a.py", "missing.py", "a.py"], reason=""),
        CommitBatch(title="b", paths=["a.py", "b.py"], reason=""),
    ]
    out = normalize_commit_batches(
        batches, allowed_paths=["a.py", "b.py", "c.py"], chinese=True
    )
    assert [b.paths for b in out] == [["a.py"], ["b.py"], ["c.py"]]
    assert out[-1].title == "其余改动"


def test_fallback_commit_batches_by_directory() -> None:
    batches = fallback_commit_batches(
        ["src/a.py", "src/b.py", "README.md"],
        chinese=False,
        max_files_per_batch=10,
    )
    keys = {tuple(b.paths) for b in batches}
    assert ("src/a.py", "src/b.py") in keys or ("src/a.py",) in keys
    assert any("README.md" in b.paths for b in batches)


def test_parse_batch_message_lang_spec() -> None:
    assert parse_batch_message_lang_spec("en,cn,en", 3) == ["en", "cn", "en"]
    assert parse_batch_message_lang_spec("1=en,2=cn,3=en", 3) == ["en", "cn", "en"]
    assert parse_batch_message_lang_spec("1:中文 2:英文", 2) == ["cn", "en"]
    assert parse_batch_message_lang_spec("en,cn", 3) is None
    assert parse_batch_message_lang_spec("1=en,2=xx", 2) is None


def test_list_change_entries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new\n", encoding="utf-8")

    entries = list_change_entries()
    paths = {e.path for e in entries}
    assert "a.txt" in paths
    assert "b.txt" in paths
    groups = stageable_paths_summary(entries)
    assert "b.txt" in groups["untracked"]
    assert "a.txt" in groups["unstaged"]
