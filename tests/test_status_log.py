"""Tests for gai status / gai log wrappers and HTML report."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from gai.common.git import collect_log_entries, log_plain, status_plain
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
    html = path1.read_text(encoding="utf-8")
    assert "td.when" in html or ".when" in html
    assert "white-space: nowrap" in html
    assert 'class="when"' in html
    assert path1.is_file()
    first = path1.read_text(encoding="utf-8")
    assert "feat: first" in first
    assert "gai-log-data" in first
    assert "branch-select" in first
    assert "commitsByBranch" in first

    (repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "fix: second")
    path2 = write_log_report(chinese=False, max_count=10, graph=False)
    assert path2 == path1
    second = path2.read_text(encoding="utf-8")
    assert "fix: second" in second



def test_write_log_report_embeds_all_local_branches(repo: Path) -> None:
    import json

    _git(repo, "checkout", "-b", "feature/x")
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-m", "feat: on feature")
    _git(repo, "checkout", "main")

    path = write_log_report(chinese=True, max_count=20, graph=False)
    html = path.read_text(encoding="utf-8")
    raw = html.split('id="gai-log-data"', 1)[1]
    raw = raw.split(">", 1)[1].split("</script>", 1)[0]
    data = json.loads(raw)
    assert data["branch"] == "main"
    assert "main" in data["branches"]
    assert "feature/x" in data["branches"]
    assert "feat: on feature" in {
        c["subject"] for c in data["commitsByBranch"]["feature/x"]
    }
    assert "feat: on feature" not in {c["subject"] for c in data["commits"]}
    assert 'id="branch-select"' in html


def test_cli_status_and_log(repo: Path) -> None:
    assert run(["status", "--cn"]) == 0
    assert run(["status", "-p", "--cn"]) == 0
    assert run(["log", "-n", "5", "--cn"]) == 0
    assert run(["log", "-p", "-g", "-n", "5", "--cn"]) == 0
    assert run(["log", "--html", "-n", "5", "--cn"]) == 0
    assert log_report_path(repo).is_file()


def test_pretty_log_folds_long_subject(repo: Path) -> None:
    from gai.git_views import _display_width, render_pretty_log

    chunk = "review-fix: add missing APIs and deploy docs. "
    long = (chunk * 10).strip()
    (repo / "a.txt").write_text("wrap\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", long)
    # height required: Rich dumb-terminal ignores width unless both are set
    console = Console(record=True, width=80, height=40)
    render_pretty_log(console, chinese=False, max_count=3, graph=False)
    out = console.export_text()
    # Pre-wrapped across multiple table lines, not ellipsis-cropped.
    assert out.count("review-fix") >= 3
    assert "deploy docs." in out
    assert "HEAD -> main" in out or "HEAD" in out
    # ASCII grid: every data line same display width, 5 pipes, no soft-wrap.
    body_lines = [ln for ln in out.splitlines() if ln.startswith("|")]
    assert len(body_lines) >= 4
    assert {ln.count("|") for ln in body_lines} == {5}
    assert len({_display_width(ln) for ln in body_lines}) == 1
    assert max(_display_width(ln) for ln in body_lines) <= 79


def test_pretty_log_cjk_subject_keeps_borders(repo: Path) -> None:
    from gai.git_views import _display_width, render_pretty_log

    long = "阶段五：完善代码审查与部署文档并补充缺失的接口说明。" * 3
    (repo / "b.txt").write_text("cjk\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", long)
    console = Console(record=True, width=80, height=40)
    render_pretty_log(console, chinese=True, max_count=3, graph=False)
    out = console.export_text()
    assert "阶段五" in out
    grid = [ln for ln in out.splitlines() if ln[:1] in "|+"]
    assert len(grid) >= 5
    assert len({_display_width(ln) for ln in grid}) == 1
    assert max(_display_width(ln) for ln in grid) <= 79
    assert all(ln.endswith("|") or ln.endswith("+") for ln in grid)
    # No Unicode box-drawing (ambiguous width on Windows CJK).
    assert not any(ch in out for ch in "│─┌┐└┘├┤┬┴┼")


def test_pretty_log_narrow_uses_stacked(repo: Path) -> None:
    from gai.git_views import render_pretty_log

    console = Console(record=True, width=50, height=24)
    render_pretty_log(console, chinese=False, max_count=2, graph=False)
    out = console.export_text()
    assert "Hash" not in out  # no grid header in stacked mode
    assert "feat: first" in out or "Tester" in out


def test_pretty_log_adapts_to_width(repo: Path) -> None:
    from gai.git_views import _display_width, render_pretty_log

    long = "阶段二：完善登录鉴权与 RequirePermissionFilter 相关逻辑。" * 2
    (repo / "c.txt").write_text("w\n", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-m", long)
    for width in (60, 80, 100, 120):
        console = Console(record=True, width=width, height=40)
        render_pretty_log(console, chinese=True, max_count=2, graph=False)
        out = console.export_text()
        assert "阶段二" in out
        lines = [ln for ln in out.splitlines() if ln[:1] in "|+"]
        if lines:
            assert max(_display_width(ln) for ln in lines) <= width
            assert len({_display_width(ln) for ln in lines}) == 1
