"""CLI-level tests for gai review / commit (no real LLM)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gai.cli import run
from gai.review import ReviewResult


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
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    return repo


def _fake_review(**_kwargs) -> ReviewResult:
    return ReviewResult(
        summary="looks fine",
        commit_message="chore: update a.txt",
        parsed_ok=True,
    )


def test_review_json_happy_path(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gai.commands.ship.run_review", _fake_review)
    code = run(["review", "--json"])
    assert code == 0


def test_review_no_staged_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    code = run(["review", "--cn"])
    assert code == 1


def test_commit_no_ai_yes(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    def boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("LLM must not be called with --no-ai")

    monkeypatch.setattr("gai.commands.ship.run_review", boom)
    monkeypatch.setattr(
        "gai.commands.ship.git_commit",
        lambda msg: called.append(msg),
    )
    code = run(["commit", "--no-ai", "-m", "chore: manual", "-y"])
    assert code == 0
    assert called == ["chore: manual"]


def test_commit_ai_yes_uses_model_message(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr("gai.commands.ship.run_review", _fake_review)
    monkeypatch.setattr(
        "gai.commands.ship.git_commit",
        lambda msg: called.append(msg),
    )
    code = run(["commit", "-y", "--cn"])
    assert code == 0
    assert called == ["chore: update a.txt"]


def test_review_diff_too_large_json(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "gai.commands.ship.staged_diff_size",
        lambda **_k: (90_000, 100, True),
    )

    def boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("LLM must not run when diff exceeds limit")

    monkeypatch.setattr("gai.commands.ship.run_review", boom)
    code = run(["review", "--json"])
    assert code == 1


def test_suggest_split_not_called_by_default(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits: list[str] = []

    def track_suggest(**_k):
        hits.append("suggest")

    monkeypatch.setattr(
        "gai.commands.ship._maybe_suggest_optional_splitflow", track_suggest
    )
    monkeypatch.setattr("gai.commands.ship.run_review", _fake_review)
    monkeypatch.setattr(
        "gai.commands.ship.staged_diff_size",
        lambda **_k: (10, 80_000, False),
    )
    code = run(["review"])
    assert code == 0
    assert hits == []
