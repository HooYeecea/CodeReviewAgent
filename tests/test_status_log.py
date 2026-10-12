"""Tests for gai status / gai log wrappers and HTML report."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from gai.git_ops import collect_log_entries, log_plain, status_plain
from gai.git_views import log_report_path, render_pretty_status, write_log_report
from gai.cli import run


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError((result.stderr or result.stdout or "git failed").strip())


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tester")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-m", "feat: first")
    (root / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    (root / "b.txt").write_text("new\n", encoding="utf-8")
    return root


def test_status_plain_and_pretty(repo: Path) -> None:
    text = status_plain(repo)
    assert "a.txt" in text or "modified" in text.lower() or "Changes" in text
    console = Console(record=True, width=100)
    render_pretty_status(console, chinese=True)
    out = console.export_text()
    assert "a.txt" in out
    assert "b.txt" in out


def test_collect_log_and_plain(repo: Path) -> None:
    entries = collect_log_entries(repo, max_count=5)
    assert entries
    assert entries[0].subject.startswith("feat:")
    plain = log_plain(repo, max_count=5, graph=False)
    assert "feat:" in plain
    graph = log_plain(repo, max_count=5, graph=True)
    assert "feat:" in graph


def test_write_log_report_overwrites(repo: Path) -> None:
    path1 = write_log_report(chinese=True, max_count=10, graph=True)
    assert path1 == log_report_path(repo)
    assert path1.is_file()
    first = path1.read_text(encoding="utf-8")
    assert "feat: first" in first
    assert "gai-log-data" in first

    (repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "fix: second")
    path2 = write_log_report(chinese=False, max_count=10, graph=False)
    assert path2 == path1
    second = path2.read_text(encoding="utf-8")
    assert "fix: second" in second


def test_cli_status_and_log(repo: Path) -> None:
    assert run(["status", "--cn"]) == 0
    assert run(["status", "-p", "--cn"]) == 0
    assert run(["log", "-n", "5", "--cn"]) == 0
    assert run(["log", "-p", "-g", "-n", "5", "--cn"]) == 0
    assert run(["log", "--html", "-n", "5", "--cn"]) == 0
    assert log_report_path(repo).is_file()
