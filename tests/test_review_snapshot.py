"""Real-index regressions for external staging and review-to-commit guards."""

import subprocess

import pytest

from gai.common.git import (
    GitError, commit, get_staged_diff, has_staged_changes, staged_snapshot,
)
from gai.flow.lib import _commit_fixed_message, _pick_and_commit_message, _run_staged_review
from gai.common.llm.client import LLMError


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Tester")
    (tmp_path / "a.txt").write_text("one\n")
    git(tmp_path, "add", "a.txt")
    return tmp_path


def test_external_add_invalidates_cached_diff(repo):
    first, _ = get_staged_diff()
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    second, _ = get_staged_diff()
    assert first != second
    assert "+two" in second


def test_external_unstage_invalidates_presence_cache(repo):
    assert has_staged_changes()
    git(repo, "rm", "--cached", "a.txt")
    assert not has_staged_changes()


def test_unborn_head_snapshot_can_commit(repo):
    snapshot = staged_snapshot()
    assert snapshot.head == ""
    commit("feat: initial", expected_snapshot=snapshot)
    assert git(repo, "show", "HEAD:a.txt") == b"one\n"


def test_branch_switch_invalidates_review_even_with_identical_tree(repo):
    git(repo, "commit", "-m", "initial")
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    snapshot = staged_snapshot()
    git(repo, "switch", "-c", "other")
    with pytest.raises(GitError) as caught:
        commit("fix: wrong branch", expected_snapshot=snapshot)
    assert caught.value.code == "review_changed"


def test_head_change_invalidates_review(repo):
    git(repo, "commit", "-m", "initial")
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    snapshot = staged_snapshot()
    git(repo, "commit", "-m", "external")
    with pytest.raises(GitError) as caught:
        commit("fix: stale", expected_snapshot=snapshot)
    assert caught.value.code == "review_changed"


def test_auto_continue_stops_on_invalid_review(repo, monkeypatch):
    monkeypatch.setattr("gai.review.engine.LLMClient.chat", lambda *a, **k: '{}')
    with pytest.raises(LLMError) as caught:
        _run_staged_review(chinese=False, review_cn=False, flush=lambda _: None,
                           auto_continue=True)
    assert caught.value.kind == "bad_response"


def test_fixed_batch_commit_rejects_changed_index(repo):
    snapshot = staged_snapshot()
    (repo / "a.txt").write_text("unreviewed\n")
    git(repo, "add", "a.txt")
    with pytest.raises(GitError) as caught:
        _commit_fixed_message("fix: batch", chinese=False, flush=lambda _: None,
                              confirm=False, expected_snapshot=snapshot)
    assert caught.value.code == "review_changed"


def test_bilingual_commit_rechecks_after_message_generation(repo, monkeypatch):
    from gai.flow.devflow import BilingualMessages

    snapshot = staged_snapshot()

    def messages(**kwargs):
        (repo / "a.txt").write_text("unreviewed\n")
        git(repo, "add", "a.txt")
        return BilingualMessages(message_en="fix: batch", message_cn="")

    monkeypatch.setattr("gai.flow.lib.suggest_bilingual_messages", messages)
    monkeypatch.setattr("gai.flow.lib.Confirm.ask", lambda *a, **k: True)
    with pytest.raises(GitError) as caught:
        _pick_and_commit_message(chinese=False, flush=lambda _: None, prefer_lang="en",
                                 expected_snapshot=snapshot)
    assert caught.value.code == "review_changed"
