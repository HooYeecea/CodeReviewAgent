"""Tests for git diff ignore filtering and remote selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.common.git import (
    GitError,
    GitResult,
    add,
    choose_remote,
    current_repo_identity,
    filter_addable_paths,
    filter_diff_by_ignore,
    has_staged_changes,
    is_local_gai_path,
    is_path_ignored,
    list_change_entries,
)


SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 111..222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 print("hi")
+print("there")
diff --git a/package-lock.json b/package-lock.json
index aaa..bbb 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-{}
+{"lock": true}
diff --git a/assets/logo.png b/assets/logo.png
index ccc..ddd 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""


def test_filter_removes_lock_and_images():
    filtered = filter_diff_by_ignore(
        SAMPLE_DIFF,
        ("package-lock.json", "*.png"),
    )
    assert "src/app.py" in filtered
    assert "package-lock.json" not in filtered
    assert "logo.png" not in filtered
    assert 'print("there")' in filtered


def test_filter_noop_without_patterns():
    assert filter_diff_by_ignore(SAMPLE_DIFF, ()) == SAMPLE_DIFF


def test_filter_empty_diff():
    assert filter_diff_by_ignore("", ("*.png",)) == ""


def test_choose_remote_prefers_origin():
    assert choose_remote(["upstream", "origin"]) == "origin"


def test_choose_remote_single():
    assert choose_remote(["company"]) == "company"


def test_choose_remote_explicit():
    assert choose_remote(["origin", "backup"], preferred="backup") == "backup"


def test_choose_remote_missing_raises():
    with pytest.raises(GitError, match="No git remote"):
        choose_remote([])
    with pytest.raises(GitError, match="not found"):
        choose_remote(["origin"], preferred="nope")
    with pytest.raises(GitError, match="Multiple remotes"):
        choose_remote(["a", "b"])


def test_current_repo_identity_prefers_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[tuple[str, ...]] = []

    def fake_run_git(*args: str, cwd=None, trace: bool = True):
        calls.append(args)
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return GitResult(str(tmp_path / "MyRepo"), "", 0)
        if args == ("remote",):
            return GitResult("upstream\norigin\n", "", 0)
        return GitResult("", "unexpected", 1)

    monkeypatch.setattr("gai.common.git.logview.run_git", fake_run_git)
    repo_name, remote_name = current_repo_identity(tmp_path)
    assert repo_name == "MyRepo"
    assert remote_name == "origin"


def test_current_repo_identity_no_remote_is_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def fake_run_git(*args: str, cwd=None, trace: bool = True):
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return GitResult(str(tmp_path / "LocalOnly"), "", 0)
        if args == ("remote",):
            return GitResult("", "", 0)
        return GitResult("", "unexpected", 1)

    monkeypatch.setattr("gai.common.git.logview.run_git", fake_run_git)
    repo_name, remote_name = current_repo_identity(tmp_path)
    assert repo_name == "LocalOnly"
    assert remote_name is None


def test_is_local_gai_path() -> None:
    assert is_local_gai_path(".gai/commands.jsonl")
    assert is_local_gai_path(".gai\\usage.jsonl")
    assert is_local_gai_path("./.gai/history-report.html")
    assert is_local_gai_path(".gai")
    assert not is_local_gai_path("src/gai/cli.py")
    assert not is_local_gai_path("README.md")


def _init_repo(tmp_path: Path) -> None:
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


def test_add_skips_ignored_gai_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit git add of ignored .gai files must not raise (splitflow last batch)."""
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".gai/\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    gai = tmp_path / ".gai"
    gai.mkdir()
    (gai / "commands.jsonl").write_text("{}\n", encoding="utf-8")
    (gai / "usage.jsonl").write_text("{}\n", encoding="utf-8")

    assert is_path_ignored(".gai/commands.jsonl")
    filtered = filter_addable_paths(
        [
            "src/app.py",
            ".gai/commands.jsonl",
            ".gai/usage.jsonl",
            ".gai/history-report.html",
        ]
    )
    assert filtered == ["src/app.py"]

    # Would previously fail with: paths are ignored by one of your .gitignore files
    add(
        [
            ".gai/commands.jsonl",
            ".gai/usage.jsonl",
            ".gai/history-data.js",
            ".gai/usage-data.js",
            ".gai/history-report.html",
        ]
    )
    assert not has_staged_changes()

    add(["src/app.py", ".gai/commands.jsonl"])
    assert has_staged_changes()
    staged = {e.path for e in list_change_entries() if e.staged}
    assert staged == {"src/app.py"}


def test_list_change_entries_hides_local_gai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "keep.py").write_text("x\n", encoding="utf-8")
    gai = tmp_path / ".gai"
    gai.mkdir()
    (gai / "commands.jsonl").write_text("{}\n", encoding="utf-8")

    paths = {e.path for e in list_change_entries()}
    assert "keep.py" in paths
    assert not any(p.startswith(".gai") for p in paths)
