"""Tests for gai graph HTML IDEA Log-style visualization."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gai.cli import run
from gai.git_ops import GitError, collect_graph_snapshot
from gai.graph_report import (
    graph_data_path,
    graph_report_path,
    write_graph_report,
)


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
    _git(root, "commit", "-m", "feat: first\n\nbody line")
    return root


def test_collect_graph_snapshot_multi_branch(repo: Path) -> None:
    _git(repo, "checkout", "-b", "feature/x")
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-m", "feat: on feature")
    _git(repo, "checkout", "main")
    _git(repo, "remote", "add", "origin", "https://example.com/demo.git")

    snap = collect_graph_snapshot(max_count=20)
    assert snap["branch"] == "main"
    assert snap["repoName"] == repo.name
    assert snap["remoteName"] == "origin"
    assert snap["remoteUrl"] == "https://example.com/demo.git"
    names = {b["name"] for b in snap["branches"]}  # type: ignore[index]
    assert "main" in names and "feature/x" in names
    subjects = {c["subject"] for c in snap["commits"]}  # type: ignore[index]
    assert "feat: first" in subjects
    assert "feat: on feature" in subjects
    first = next(c for c in snap["commits"] if c["subject"] == "feat: first")  # type: ignore[index]
    assert first["email"] == "t@example.com"
    assert "body line" in str(first.get("body") or "")


def test_write_graph_report_and_overwrite(repo: Path) -> None:
    path1 = write_graph_report(chinese=True, max_count=10)
    assert path1 == graph_report_path(repo)
    assert path1.is_file()
    assert graph_data_path(repo).is_file()
    html = path1.read_text(encoding="utf-8")
    assert "btn-refresh" in html
    assert "graph-data.js" in html
    assert "graph-app.js" in html
    assert (path1.parent / "graph-app.js").is_file()
    assert "graph-table" in html
    assert "drawer" in html
    assert "tooltip" in html
    assert "btn-collapse" in html
    assert "btn-expand" in html
    assert "GaiGraphApp.createApp" in html
    assert "branch-checks" in html
    assert "cdn.jsdelivr.net/npm/echarts" not in html
    assert "echarts.min.js" not in html
    assert "GitgraphJS" not in html
    assert "type: \"graph\"" not in (path1.parent / "graph-app.js").read_text(encoding="utf-8")
    app_js = (path1.parent / "graph-app.js").read_text(encoding="utf-8")
    assert "buildVisibleModel" in app_js
    assert "drawCellSvg" in app_js
    assert "fold-hit" in app_js
    assert "toEchartsGraph" not in app_js
    data_txt = graph_data_path(repo).read_text(encoding="utf-8")
    assert "commits" in data_txt
    assert "GAI_GRAPH_DATA" in data_txt

    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "feat: second")
    path2 = write_graph_report(chinese=False, max_count=10)
    assert path2 == path1
    assert "feat: second" in graph_data_path(repo).read_text(encoding="utf-8")


def test_graph_not_repo_friendly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(GitError) as exc:
        collect_graph_snapshot()
    assert exc.value.code == "not_repo"
    assert run(["graph", "--no-open", "--cn"]) == 1


def test_cli_graph_no_open(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[Path] = []

    def _fake_open(path: Path, *, prefer_http: bool = False) -> str:
        opened.append(path)
        return path.as_uri()

    monkeypatch.setattr("gai.commands.view.open_path", _fake_open)
    assert run(["graph", "--no-open", "--cn"]) == 0
    assert not opened
    raw = graph_data_path(repo).read_text(encoding="utf-8")
    payload = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    assert payload["initialLang"] == "cn"
    assert payload["commits"]


def test_graph_layout_js_helpers() -> None:
    script = Path(__file__).resolve().parent / "test_graph_layout.js"
    node = subprocess.run(
        ["node", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    if node.returncode == 127 or "not recognized" in (node.stderr or "").lower():
        pytest.skip("node not available")
    if node.returncode != 0 and "ENOENT" in (node.stderr or ""):
        pytest.skip("node not available")
    assert node.returncode == 0, (node.stdout or "") + (node.stderr or "")
    assert "OK" in (node.stdout or "")


def test_cli_graph_opens_by_default(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[Path] = []

    def _fake_open(path: Path, *, prefer_http: bool = False) -> str:
        opened.append(path)
        return path.as_uri()

    monkeypatch.setattr("gai.commands.view.open_path", _fake_open)
    assert run(["graph", "--cn"]) == 0
    assert opened and opened[0] == graph_report_path(repo)
