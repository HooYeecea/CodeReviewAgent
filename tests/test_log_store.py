"""Global + local dual-write and legacy merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gai.command_history import CommandRecord, append_command_record, load_command_records
from gai.llm.history import UsageRecord, append_usage_record, load_usage_records
from gai import log_store


@pytest.fixture
def dual_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    local_root = tmp_path / "NatureLanguageCRUD"
    local_root.mkdir()
    global_dir = tmp_path / "home_gai"
    global_dir.mkdir()
    monkeypatch.setattr(log_store, "CONFIG_DIR", global_dir)
    monkeypatch.setattr("gai.config.CONFIG_DIR", global_dir)
    monkeypatch.setattr(log_store, "project_root", lambda cwd=None: local_root)
    monkeypatch.setattr("gai.llm.history.project_root", lambda cwd=None: local_root)
    monkeypatch.delenv("GAI_USAGE_LOG", raising=False)
    monkeypatch.delenv("GAI_USAGE_LOG_GLOBAL", raising=False)
    monkeypatch.delenv("GAI_HISTORY_LOG", raising=False)
    monkeypatch.delenv("GAI_HISTORY_LOG_GLOBAL", raising=False)
    return local_root, global_dir


def test_dual_write_usage(dual_roots: tuple[Path, Path]) -> None:
    local_root, global_dir = dual_roots
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T10:00:00+08:00",
            git_user="A",
            git_email="a@x.com",
            repo_name="NatureLanguageCRUD",
            provider="deepseek",
            model="deepseek-chat",
            action="review",
            total_tokens=10,
        )
    )
    local = local_root / ".gai" / "usage.jsonl"
    global_p = global_dir / "usage.jsonl"
    assert local.is_file()
    assert global_p.is_file()
    assert len(load_usage_records(path=local)) == 1
    assert len(load_usage_records(path=global_p)) == 1


def test_dual_write_commands(dual_roots: tuple[Path, Path]) -> None:
    local_root, global_dir = dual_roots
    append_command_record(
        CommandRecord(
            ts="2026-10-07T10:00:00+08:00",
            command="commit",
            argv=["commit", "--cn"],
            exit_code=0,
            ok=True,
            repo_name="NatureLanguageCRUD",
        )
    )
    local = local_root / ".gai" / "commands.jsonl"
    global_p = global_dir / "commands.jsonl"
    assert local.is_file() and global_p.is_file()
    assert len(load_command_records(path=local)) == 1
    assert len(load_command_records(path=global_p)) == 1


def test_merge_two_repos_into_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "pythonProject"
    cra = parent / "CodeReviewAgent"
    nlc = parent / "NatureLanguageCRUD"
    for repo, name in ((cra, "CodeReviewAgent"), (nlc, "NatureLanguageCRUD")):
        gai = repo / ".gai"
        gai.mkdir(parents=True)
        (gai / "usage.jsonl").write_text(
            json.dumps(
                {
                    "ts": f"2026-10-07T1{0 if name.startswith('C') else 1}:00:00+08:00",
                    "git_user": "u",
                    "git_email": "u@x.com",
                    "action": "review",
                    "total_tokens": 1,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (gai / "commands.jsonl").write_text(
            json.dumps(
                {
                    "ts": f"2026-10-07T1{0 if name.startswith('C') else 1}:00:00+08:00",
                    "command": "usage",
                    "argv": ["usage", "--cn"],
                    "exit_code": 0,
                    "ok": True,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    global_dir = tmp_path / "home_gai"
    global_dir.mkdir()
    monkeypatch.setattr(log_store, "CONFIG_DIR", global_dir)
    monkeypatch.setattr(log_store, "project_root", lambda cwd=None: cra)

    stats = log_store.ensure_global_logs_merged(cwd=cra)
    assert stats["usage"] == 2
    assert stats["commands"] == 2

    usage_rows = load_usage_records(path=global_dir / "usage.jsonl")
    repos = {r.repo_name for r in usage_rows}
    assert repos == {"CodeReviewAgent", "NatureLanguageCRUD"}

    # Idempotent second merge.
    stats2 = log_store.ensure_global_logs_merged(cwd=cra)
    assert stats2["usage"] == 0
    assert stats2["commands"] == 0
    assert len(load_usage_records(path=global_dir / "usage.jsonl")) == 2


def test_explicit_path_skips_dual_write(dual_roots: tuple[Path, Path], tmp_path: Path) -> None:
    _local_root, global_dir = dual_roots
    only = tmp_path / "only.jsonl"
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T10:00:00+08:00",
            git_user="A",
            git_email="a@x.com",
            action="review",
            total_tokens=3,
        ),
        path=only,
    )
    assert only.is_file()
    assert not (global_dir / "usage.jsonl").exists()
