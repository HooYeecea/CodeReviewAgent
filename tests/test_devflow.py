"""Tests for gai devflow helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from gai.devflow import (
    normalize_path_input,
    parse_bilingual_messages,
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
