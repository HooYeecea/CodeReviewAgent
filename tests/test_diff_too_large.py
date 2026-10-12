"""Tests for staged-diff size guard and DiffTooLargeError."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.config import Settings
from gai.review import DiffTooLargeError, run_review, staged_diff_size


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
def staged_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "a.txt").write_text("x" * 5000 + "\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    return repo


def test_staged_diff_size_detects_exceed(staged_repo: Path) -> None:
    settings = Settings(max_diff_chars=100)
    chars, limit, exceeds = staged_diff_size(settings=settings)
    assert chars > 100
    assert limit == 100
    assert exceeds is True


def test_run_review_blocks_truncated_by_default(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(max_diff_chars=100, api_key="test-key")

    def boom(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("LLM should not be called when diff is too large")

    monkeypatch.setattr("gai.review.LLMClient.chat", boom)
    with pytest.raises(DiffTooLargeError) as caught:
        run_review(settings=settings, review_only=True)
    assert caught.value.limit == 100
    assert caught.value.chars > 100


def test_run_review_allow_truncated(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(max_diff_chars=100, api_key="test-key")

    def fake_chat(self, *, system: str, user: str) -> str:  # noqa: ARG001
        return (
            '{"summary":"ok","commit_message":"chore: big",'
            '"review":[]}'
        )

    monkeypatch.setattr("gai.review.LLMClient.chat", fake_chat)
    result = run_review(
        settings=settings, review_only=True, allow_truncated=True
    )
    assert result.truncated_diff is True
