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
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
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

    monkeypatch.setattr("gai.commit.cmd.run_review", boom)
    monkeypatch.setattr(
        "gai.commit.cmd.git_commit",
        lambda msg, **kwargs: called.append(msg),
    )
    code = run(["commit", "--no-ai", "-m", "chore: manual", "-y"])
    assert code == 0
    assert called == ["chore: manual"]


def test_commit_ai_yes_uses_model_message(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr("gai.commit.cmd.run_review", _fake_review)
    monkeypatch.setattr(
        "gai.commit.cmd.git_commit",
        lambda msg, **kwargs: called.append(msg),
    )
    code = run(["commit", "-y", "--cn"])
    assert code == 0
    assert called == ["chore: update a.txt"]


def test_review_diff_too_large_json(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gai.review import StagedDiffInfo

    monkeypatch.setattr(
        "gai.review.cmd.load_staged_diff_info",
        lambda **_k: StagedDiffInfo(text="x" * 200, chars=90_000, limit=100, exceeds=True),
    )

    def boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("LLM must not run when diff exceeds limit")

    monkeypatch.setattr("gai.review.cmd.run_review", boom)
    code = run(["review", "--json"])
    assert code == 1


def test_suggest_split_not_called_by_default(
    staged_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gai.review import StagedDiffInfo

    hits: list[str] = []

    def track_suggest(**_k):
        hits.append("suggest")

    monkeypatch.setattr(
        "gai.review.helpers._maybe_suggest_optional_splitflow", track_suggest
    )
    monkeypatch.setattr("gai.review.cmd.run_review", _fake_review)
    monkeypatch.setattr(
        "gai.review.cmd.load_staged_diff_info",
        lambda **_k: StagedDiffInfo(text="ok\n", chars=10, limit=80_000, exceeds=False),
    )
    code = run(["review"])
    assert code == 0
    assert hits == []


def _head(repo):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).strip()


@pytest.mark.parametrize("args", [
    ["review"], ["review", "--json"], ["commit", "-y"],
    ["commit", "-m", "fix: manual", "-y"],
])
def test_invalid_review_stops_cli(staged_repo, monkeypatch, args):
    monkeypatch.setattr("gai.review.engine.LLMClient.chat", lambda *a, **k: '{}')
    before = _head(staged_repo)
    assert run(args) == 1
    assert _head(staged_repo) == before


def test_commit_stops_if_external_add_during_model_call(staged_repo, monkeypatch):
    def chat(*args, **kwargs):
        (staged_repo / "unexpected.txt").write_text("not reviewed\n")
        _git(staged_repo, "add", "unexpected.txt")
        return '{"review":[],"commit_message":"fix: reviewed"}'

    monkeypatch.setattr("gai.review.engine.LLMClient.chat", chat)
    before = _head(staged_repo)
    assert run(["commit", "-y"]) == 1
    assert _head(staged_repo) == before


def test_commit_stops_if_external_add_during_confirmation(staged_repo, monkeypatch):
    monkeypatch.setattr("gai.review.engine.LLMClient.chat", lambda *a, **k:
                        '{"review":[],"commit_message":"fix: reviewed"}')

    def confirm(*args, **kwargs):
        (staged_repo / "unexpected.txt").write_text("not reviewed\n")
        _git(staged_repo, "add", "unexpected.txt")
        return True

    monkeypatch.setattr("gai.commit.cmd.Confirm.ask", confirm)
    before = _head(staged_repo)
    assert run(["commit"]) == 1
    assert _head(staged_repo) == before


def test_reviewed_commit_allows_unstaged_edit(staged_repo, monkeypatch):
    def chat(*args, **kwargs):
        (staged_repo / "a.txt").write_text("keep this unstaged\n")
        return '{"review":[],"commit_message":"fix: reviewed"}'

    monkeypatch.setattr("gai.review.engine.LLMClient.chat", chat)
    assert run(["commit", "-y"]) == 0
    committed = subprocess.check_output(["git", "show", "HEAD:a.txt"], cwd=staged_repo)
    assert committed == b"hello world\n"
    assert (staged_repo / "a.txt").read_text() == "keep this unstaged\n"
