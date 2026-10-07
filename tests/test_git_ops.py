"""Tests for git diff ignore filtering and remote selection."""

from pathlib import Path

import pytest

from gai.git_ops import (
    GitError,
    GitResult,
    choose_remote,
    current_repo_identity,
    filter_diff_by_ignore,
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

    monkeypatch.setattr("gai.git_ops.run_git", fake_run_git)
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

    monkeypatch.setattr("gai.git_ops.run_git", fake_run_git)
    repo_name, remote_name = current_repo_identity(tmp_path)
    assert repo_name == "LocalOnly"
    assert remote_name is None
