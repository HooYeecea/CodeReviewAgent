"""Real Git paths and hooks: ignored data stays out, reviewed commits stay pinned."""
import json

import pytest

from test_review_snapshot import repo, git  # noqa: F401
from gai.common.git import GitError, commit, get_staged_diff, staged_snapshot, filter_diff_by_ignore
from gai.common.git.local import get_unstaged_diff, clear_diff_cache
from gai.review import ReviewResult
from gai.cli import run


@pytest.mark.parametrize("quoted", ["true", "false"])
def test_unicode_spaces_and_ambiguous_separators_are_filtered(repo, quoted):
    git(repo, "config", "core.quotepath", quoted)
    for name in ("私密.env", "space name.env", "folder b/secret.env", "保留.py"):
        path = repo / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("IGNORE_ME\n" if name.endswith(".env") else "KEEP_ME\n", encoding="utf-8")
        git(repo, "add", "--", name)
    text, _ = get_staged_diff(ignore_patterns=["*.env"])
    assert "IGNORE_ME" not in text
    assert "KEEP_ME" in text


@pytest.mark.parametrize("operation", ["rename", "delete", "binary"])
def test_renames_deletions_and_binary_paths(repo, operation):
    (repo / "旧 秘密.env").write_text("SECRET\n", encoding="utf-8")
    git(repo, "add", "--", "旧 秘密.env")
    git(repo, "commit", "-m", "base")
    if operation == "rename":
        git(repo, "mv", "旧 秘密.env", "new public.py")
    elif operation == "delete":
        git(repo, "rm", "--", "旧 秘密.env")
    else:
        (repo / "旧 秘密.env").write_bytes(b"\0BINARY_SECRET")
        git(repo, "add", "--", "旧 秘密.env")
    assert get_staged_diff(ignore_patterns=["*.env"])[0] == ""


def test_custom_prefix_relative_config_and_untracked_names(repo):
    git(repo, "commit", "-m", "base")
    git(repo, "config", "diff.noprefix", "true")
    git(repo, "config", "diff.relative", "true")
    child = repo / "sub"
    child.mkdir()
    (repo / "a.txt").write_text("TOP_LEVEL_SECRET\n")
    (child / "忽略.env").write_text("untracked")
    (child / "keep.py").write_text("untracked")
    clear_diff_cache()
    text, _ = get_unstaged_diff(child, ignore_patterns=["a.txt", "sub/*.env"])
    assert "TOP_LEVEL_SECRET" not in text
    assert "忽略.env" not in text
    assert "keep.py" in text


@pytest.mark.parametrize("path", ['tab\tname.env', 'quote"name.env', 'back\\slash.env', 'line\nname.env'])
def test_c_quoted_paths_any_platform(path):
    left, right = json.dumps("a/" + path), json.dumps("b/" + path)
    patch = f"diff --git {left} {right}\nnew file mode 100644\n+SECRET\n"
    assert filter_diff_by_ignore(patch, ["*.env"]) == ""


def test_unknown_paths_fail_closed():
    with pytest.raises(GitError, match="Cannot safely filter"):
        filter_diff_by_ignore("diff --git unknown header\n+SECRET\n", ["*.env"])


def hook(repo, name, script):
    path = repo / "hooks"
    path.mkdir(exist_ok=True)
    git(repo, "config", "core.hooksPath", str(path))
    target = path / name
    target.write_text("#!/bin/sh\n" + script, encoding="utf-8", newline="\n")
    target.chmod(0o755)


@pytest.mark.parametrize("save", [False, True])
def test_hook_changes_stop_push_with_or_without_archive(repo, monkeypatch, save):
    git(repo, "config", "commit.gpgsign", "false")
    monkeypatch.setattr("gai.commit.cmd.run_review", lambda **k: ReviewResult(commit_message="reviewed", summary="ok"))
    monkeypatch.setattr("gai.commit.cmd._do_push", lambda **k: pytest.fail("unreviewed commit must not push"))
    hook(repo, "pre-commit", 'printf "hook changed\\n" > a.txt\nexec git add -- a.txt\n')
    args = ["commit", "--yes", "--push"] + (["--save-review"] if save else [])
    assert run(args) == 1
    assert git(repo, "show", "HEAD:a.txt") == b"hook changed\n"
    assert git(repo, "rev-list", "--count", "HEAD").strip() == b"1"


def test_post_commit_hook_changes_index_stops_flow(repo):
    snapshot = staged_snapshot(repo)
    hook(repo, "post-commit", 'printf "later\\n" > a.txt\nexec git add -- a.txt\n')
    with pytest.raises(GitError) as error:
        commit("reviewed", expected_snapshot=snapshot)
    assert error.value.code == "commit_review_mismatch"
    assert git(repo, "show", "HEAD:a.txt") == b"one\n"
    assert git(repo, "show", ":a.txt") == b"later\n"


def test_hook_rewrites_head_parent_is_detected(repo):
    git(repo, "commit", "-m", "base")
    (repo / "a.txt").write_text("reviewed\n")
    git(repo, "add", "a.txt")
    snapshot = staged_snapshot(repo)
    hook(repo, "post-commit", 'exec git -c core.hooksPath=disabled commit --allow-empty -m extra\n')
    with pytest.raises(GitError) as error:
        commit("reviewed", expected_snapshot=snapshot)
    assert error.value.code == "commit_review_mismatch"


def test_harmless_hook_allows_verified_commit(repo):
    hook(repo, "pre-commit", "exit 0\n")
    commit("reviewed", expected_snapshot=staged_snapshot(repo))
    assert git(repo, "rev-list", "--count", "HEAD").strip() == b"1"


def test_reviewed_merge_accepts_its_intended_parents(repo):
    git(repo, "commit", "-m", "base")
    git(repo, "switch", "-c", "feature")
    (repo / "feature.txt").write_text("feature\n")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    feature = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "switch", "main")
    base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "merge", "--no-ff", "--no-commit", "feature")
    commit("reviewed merge", expected_snapshot=staged_snapshot(repo))
    assert git(repo, "show", "-s", "--format=%P", "HEAD").split() == [base, feature]


def test_post_commit_snapshot_error_explains_commit_exists(repo, monkeypatch):
    snapshot = staged_snapshot(repo)
    calls = 0
    def snapshot_then_fail(cwd=None):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise GitError("cannot read index")
        return snapshot
    monkeypatch.setattr("gai.common.git.local.staged_snapshot", snapshot_then_fail)
    with pytest.raises(GitError, match="Commit created but verification failed"):
        commit("reviewed", expected_snapshot=snapshot)
    assert git(repo, "rev-list", "--count", "HEAD").strip() == b"1"
