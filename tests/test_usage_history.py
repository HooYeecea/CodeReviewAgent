"""Tests for persistent local LLM usage history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from gai.config import Settings
from gai.llm.client import LLMClient
from gai.llm.history import (
    UsageRecord,
    append_usage_record,
    format_usage_table,
    load_usage_records,
    summarize_records,
)
from gai.llm.usage import clear_llm_usage, set_llm_action


def test_usage_log_path_under_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GAI_USAGE_LOG", raising=False)
    monkeypatch.setattr("gai.llm.history.project_root", lambda cwd=None: tmp_path)
    from gai.llm.history import usage_log_path

    assert usage_log_path() == tmp_path / ".gai" / "usage.jsonl"


def test_append_and_load(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T10:00:00+08:00",
            git_user="Alice",
            git_email="alice@example.com",
            provider="deepseek",
            provider_name="DeepSeek",
            model="deepseek-chat",
            action="review",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            base_url="https://api.deepseek.com/v1",
        ),
        path=path,
    )
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T11:00:00+08:00",
            git_user="Bob",
            git_email="bob@example.com",
            provider="openai",
            provider_name="OpenAI",
            model="gpt-4o-mini",
            action="commit",
            prompt_tokens=20,
            completion_tokens=8,
            total_tokens=28,
        ),
        path=path,
    )
    rows = load_usage_records(path=path)
    assert len(rows) == 2
    assert rows[0].git_user == "Alice"
    assert rows[1].action == "commit"

    only_commit = load_usage_records(path=path, action="commit")
    assert len(only_commit) == 1
    assert only_commit[0].model == "gpt-4o-mini"

    by_user = load_usage_records(path=path, git_user="alice")
    assert len(by_user) == 1

    newest = load_usage_records(path=path, limit=1)
    assert len(newest) == 1
    assert newest[0].git_user == "Bob"

    summary = summarize_records(rows)
    assert summary.calls == 2
    assert summary.total_tokens == 43


def test_since_filter(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    now = datetime.now(timezone.utc).astimezone()
    old = (now - timedelta(days=10)).isoformat(timespec="seconds")
    recent = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    append_usage_record(
        UsageRecord(
            ts=old,
            git_user="A",
            git_email="a@x.com",
            provider="openai",
            provider_name="OpenAI",
            model="m",
            action="report",
            total_tokens=1,
        ),
        path=path,
    )
    append_usage_record(
        UsageRecord(
            ts=recent,
            git_user="A",
            git_email="a@x.com",
            provider="openai",
            provider_name="OpenAI",
            model="m",
            action="report",
            total_tokens=2,
        ),
        path=path,
    )
    since = now - timedelta(days=2)
    rows = load_usage_records(path=path, since=since)
    assert len(rows) == 1
    assert rows[0].total_tokens == 2


def test_format_usage_table_chinese(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T12:00:00+08:00",
            git_user="张三",
            git_email="z@example.com",
            provider="siliconflow",
            provider_name="SiliconFlow",
            model="Qwen/Qwen2.5",
            action="report",
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
        ),
        path=path,
    )
    # Point loader via explicit path in format by loading first
    rows = load_usage_records(path=path)
    text = format_usage_table(rows, chinese=True, group="action")
    assert "张三" in text
    assert "SiliconFlow" in text
    assert "report" in text
    assert "140" in text
    assert "按动作汇总" in text


def test_client_persists_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("GAI_USAGE_LOG", str(path))
    monkeypatch.setattr(
        "gai.llm.client.current_git_identity",
        lambda cwd=None: ("Tester", "tester@example.com"),
    )

    class _FakeResponse:
        status_code = 200
        text = ""
        headers: dict[str, str] = {}

        def json(self) -> dict:
            return {
                "model": "deepseek-chat",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 3,
                    "total_tokens": 14,
                },
            }

    class _FakeHttp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _FakeHttp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeHttp)
    clear_llm_usage()
    set_llm_action("review")
    settings = Settings(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        timeout=5.0,
    )
    client = LLMClient(settings, sleep=lambda _s: None)
    assert client.chat(system="s", user="u") == "ok"

    rows = load_usage_records(path=path)
    assert len(rows) == 1
    rec = rows[0]
    assert rec.action == "review"
    assert rec.provider == "deepseek"
    assert rec.provider_name == "DeepSeek"
    assert rec.model == "deepseek-chat"
    assert rec.git_user == "Tester"
    assert rec.git_email == "tester@example.com"
    assert rec.total_tokens == 14
