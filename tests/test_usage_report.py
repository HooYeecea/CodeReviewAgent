"""Tests for HTML usage report generation."""

from __future__ import annotations

from pathlib import Path

from gai.llm.history import UsageRecord, append_usage_record, load_usage_records
from gai.llm.usage_report import (
    build_usage_analytics,
    path_to_file_url,
    usage_report_path,
    write_usage_report,
)


def test_write_usage_report_fixed_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("gai.llm.usage_report.project_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr("gai.llm.history.project_root", lambda cwd=None: tmp_path)

    log = tmp_path / ".gai" / "usage.jsonl"
    append_usage_record(
        UsageRecord(
            ts="2026-10-07T10:00:00+08:00",
            git_user="Alice",
            git_email="a@x.com",
            provider="deepseek",
            provider_name="DeepSeek",
            model="deepseek-chat",
            action="commit",
            action_detail="review+message",
            branch="main",
            files_count=2,
            diff_chars=800,
            prompt_tokens=80,
            completion_tokens=40,
            total_tokens=120,
            ok=True,
            duration_ms=900,
        ),
        path=log,
    )
    append_usage_record(
        UsageRecord(
            ts="2026-10-08T11:00:00+08:00",
            git_user="Bob",
            git_email="b@x.com",
            provider="openai",
            provider_name="OpenAI",
            model="gpt-4o-mini",
            action="report",
            action_detail="report",
            branch="feature/x",
            commit_count=12,
            since="7d",
            prompt_tokens=30,
            completion_tokens=10,
            total_tokens=40,
            ok=False,
            error_kind="timeout",
            duration_ms=3000,
        ),
        path=log,
    )

    monkeypatch.setenv("GAI_USAGE_LOG", str(log))
    records = load_usage_records(path=log)
    out = write_usage_report(records, chinese=True)
    assert out == tmp_path / ".gai" / "usage-report.html"
    assert out == usage_report_path()
    text = out.read_text(encoding="utf-8")
    assert "gai Token 用量报告" in text
    assert "echarts" in text.lower()
    assert "DeepSeek" in text or "deepseek" in text.lower()
    assert "review+message" in text or "DATA" in text
    url = path_to_file_url(out)
    assert url.startswith("file://")
    assert "usage-report.html" in url

    analytics = build_usage_analytics(records)
    assert analytics["totals"]["calls"] == 2
    assert analytics["totals"]["tokens"] == 160
    assert analytics["totals"]["ok"] == 1
    assert analytics["totals"]["fail"] == 1
    assert "2026-10-07" in analytics["by_day"]["labels"]
    assert "main" in analytics["by_branch"]["labels"]
    assert "feature/x" in analytics["by_branch"]["labels"]
    assert analytics["token_split"]["tokens"] == [110, 50]
    assert analytics["duration_by_model"]["labels"]
    assert analytics["heatmap"]["branches"]
    assert analytics["heatmap"]["actions"]
    assert any(cell[2] > 0 for cell in analytics["heatmap"]["data"])
    assert "chart-branch" in text
    assert "chart-heat" in text

    # Re-run overwrites same file (sync)
    write_usage_report(records, chinese=False)
    text2 = out.read_text(encoding="utf-8")
    assert "gai Token Usage Report" in text2
