"""End-to-end-ish tests for splitflow (no real LLM)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import typer

from gai.flow.devflow import CommitBatch, CommitBatchPlan
from gai.flow.lib import _run_splitflow
from gai.common.git import staged_snapshot


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
def dirty_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    (repo / ".gitignore").write_text(".gai/\n", encoding="utf-8")
    (repo / "a.py").write_text("print(1)\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    (repo / "a.py").write_text("print(2)\n", encoding="utf-8")
    gai = repo / ".gai"
    gai.mkdir()
    (gai / "commands.jsonl").write_text("{}\n", encoding="utf-8")
    (gai / "usage.jsonl").write_text("{}\n", encoding="utf-8")
    return repo


def test_splitflow_drops_gai_batch_and_commits_rest(
    dirty_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Last-batch .gai artifacts must be sanitized away; real files still commit."""
    commits: list[str] = []
    prompts: list[str] = []

    plan = CommitBatchPlan(
        batches=[
            CommitBatch(
                title="code",
                paths=["a.py"],
                reason="app change",
                message_hint_en="chore: bump a.py",
                message_hint_cn="chore: 更新 a.py",
                commit_message="chore: bump a.py",
            ),
            CommitBatch(
                title="更新 .gai 运行记录与报告产物",
                paths=[
                    ".gai/commands.jsonl",
                    ".gai/usage.jsonl",
                    ".gai/history-data.js",
                    ".gai/usage-data.js",
                    ".gai/history-report.html",
                ],
                reason="runtime logs",
            ),
        ],
        summary="code then gai",
        parsed_ok=True,
    )

    # True for any mid-flow confirms; False only when asked about push.
    def confirm_ask(prompt: str = "", *a, **k):
        text = str(prompt)
        if "推送" in text or "Push" in text or "push" in text.lower():
            return False
        return True

    monkeypatch.setattr("gai.flow.lib.Confirm.ask", confirm_ask)
    monkeypatch.setattr(
        "gai.flow.lib.Prompt.ask",
        lambda *a, **k: prompts.append(str(a)) or "1",
    )
    monkeypatch.setattr(
        "gai.flow.lib._run_staged_review",
        lambda **_k: staged_snapshot(),
    )

    def fake_pick(**_k):
        from gai.flow.lib import _flow_commit

        _flow_commit("chore: bump a.py", _k["expected_snapshot"])
        commits.append("chore: bump a.py")
        return True

    monkeypatch.setattr("gai.flow.lib._pick_and_commit_message", fake_pick)
    monkeypatch.setattr(
        "gai.flow.lib._do_push",
        lambda **_k: (_ for _ in ()).throw(AssertionError("push should be skipped")),
    )

    with pytest.raises(typer.Exit) as exc:
        _run_splitflow(chinese=True, remote=None, trace=False, plan=plan)

    assert exc.value.exit_code == 0
    assert commits == ["chore: bump a.py"]
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=dirty_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "chore: bump a.py" in log.stdout
    assert ".gai/" not in log.stdout


def test_splitflow_empty_after_sanitize_exits(
    dirty_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = CommitBatchPlan(
        batches=[
            CommitBatch(
                title="gai only",
                paths=[".gai/commands.jsonl", ".gai/usage.jsonl"],
                reason="",
            )
        ],
        summary="noise",
        parsed_ok=True,
    )
    monkeypatch.setattr("gai.flow.lib.Confirm.ask", lambda *a, **k: True)
    with pytest.raises(typer.Exit) as exc:
        _run_splitflow(chinese=True, remote=None, trace=False, plan=plan)
    assert exc.value.exit_code == 1
