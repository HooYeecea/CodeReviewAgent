"""Tests for gai command execution history."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gai.cli import run
from gai.command_history import (
    CommandRecord,
    append_command_record,
    command_log_path,
    extract_command,
    format_command_table,
    history_enabled,
    load_command_records,
    maybe_record_command,
    sanitize_argv,
)


def test_sanitize_argv_masks_api_key() -> None:
    assert sanitize_argv(["config", "--api-key", "sk-secret", "--cn"]) == [
        "config",
        "--api-key",
        "***",
        "--cn",
    ]
    assert sanitize_argv(["config", "--api-key=sk-secret"]) == [
        "config",
        "--api-key=***",
    ]
    assert sanitize_argv(["review", "sk-abcdef"]) == ["review", "***"]


def test_extract_command() -> None:
    assert extract_command(["--cn", "commit", "-y"]) == ("commit", "")
    assert extract_command(["completion", "install", "--shell", "powershell"]) == (
        "completion",
        "install",
    )
    assert extract_command(["-h"]) == ("", "")


def test_append_and_load(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("gai.command_history.project_root", lambda cwd=None: tmp_path)
    log = tmp_path / ".gai" / "commands.jsonl"
    append_command_record(
        CommandRecord(
            ts="2026-10-07T10:00:00+08:00",
            command="commit",
            argv=["commit", "--cn"],
            exit_code=0,
            ok=True,
            duration_ms=120,
            git_user="Alice",
            git_email="a@x.com",
            repo_name="Demo",
        ),
        path=log,
    )
    append_command_record(
        CommandRecord(
            ts="2026-10-07T11:00:00+08:00",
            command="push",
            argv=["push", "--cn"],
            exit_code=1,
            ok=False,
            duration_ms=40,
        ),
        path=log,
    )
    rows = load_command_records(path=log)
    assert len(rows) == 2
    assert rows[0].command == "commit"
    assert rows[1].ok is False
    only_fail = load_command_records(path=log, ok=False)
    assert len(only_fail) == 1
    only_commit = load_command_records(path=log, command="commit")
    assert len(only_commit) == 1
    text = format_command_table(rows, chinese=True)
    assert "本地命令执行记录" in text
    assert "commit" in text
    assert "失败" in text


def test_history_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GAI_HISTORY", "0")
    assert history_enabled() is False
    monkeypatch.setattr("gai.command_history.project_root", lambda cwd=None: tmp_path)
    maybe_record_command(["review", "--cn"], exit_code=0, duration_ms=1)
    assert not (tmp_path / ".gai" / "commands.jsonl").exists()


def test_skip_completion_probe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GAI_HISTORY", raising=False)
    monkeypatch.setenv("_GAI_COMPLETE", "complete")
    monkeypatch.setattr("gai.command_history.project_root", lambda cwd=None: tmp_path)
    maybe_record_command(["commit"], exit_code=0, duration_ms=1)
    assert not (tmp_path / ".gai" / "commands.jsonl").exists()


def test_run_records_history(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("GAI_HISTORY_LOG", str(tmp_path / ".gai" / "commands.jsonl"))
    monkeypatch.delenv("GAI_HISTORY", raising=False)
    monkeypatch.delenv("_GAI_COMPLETE", raising=False)

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run(["guide", "--cn"])
    assert code == 0
    log = Path(tmp_path / ".gai" / "commands.jsonl")
    assert log.is_file()
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(row.get("command") == "guide" for row in lines)
    assert command_log_path() == log

    with redirect_stdout(out), redirect_stderr(err):
        code2 = run(["history", "--cn", "-n", "5"])
    assert code2 == 0
    combined = out.getvalue() + err.getvalue()
    assert "guide" in combined or "本地命令" in combined
