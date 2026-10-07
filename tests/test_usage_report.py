"""Tests for HTML usage report generation."""

from __future__ import annotations

from pathlib import Path

from gai.llm.history import UsageRecord, append_usage_record, load_usage_records
from datetime import datetime

from gai.llm.usage_report import (
    build_report_datasets,
    build_trend_series,
    build_usage_analytics,
    path_to_file_url,
    sync_usage_data_file,
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
            repo_name="CodeReviewAgent",
            remote_name="origin",
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
            repo_name="OtherApp",
            remote_name=None,
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
    data_js = (tmp_path / ".gai" / "usage-data.js").read_text(encoding="utf-8")
    assert "gai Token 用量报告" in text
    assert "echarts" in text.lower()
    assert "btn-refresh" in text
    assert "btn-export-csv" in text
    assert "btn-page-next" in text
    assert "btn-theme-dark" in text
    assert "btn-lang-cn" in text
    assert "gai-ui-theme" in text
    assert "gai-ui-lang" in text
    assert "refresh_fail_file" in text
    assert "usage-data.js" in text
    assert "window.__GAI_USAGE_DATASETS__" in data_js
    assert "DeepSeek" in data_js or "deepseek" in data_js.lower()
    assert "review+message" in data_js
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
    assert "chart-repo" in text
    assert "chart-heat" in text
    assert "chart-heat-repo" in text
    assert 'class="card scope-all"' in text or "scope-all" in text
    assert "scope-repo" in text
    assert "view-all" in text
    assert "project-dd" in text
    assert "dd-trigger" in text
    assert "trend-seg" in text
    assert "data-mode=\"today\"" in text
    assert "CodeReviewAgent" in analytics["by_repo"]["labels"]
    assert "OtherApp" in analytics["by_repo"]["labels"]
    assert analytics["heatmap_repo"]["repos"]
    datasets = build_report_datasets(records)
    assert datasets["default_project"] == "__all__"
    assert {p["id"] for p in datasets["projects"]} == {"CodeReviewAgent", "OtherApp"}
    assert datasets["by_project"]["CodeReviewAgent"]["totals"]["calls"] == 1
    assert set(analytics["trends"]) >= {
        "today",
        "last7",
        "last15",
        "week",
        "month",
        "year",
        "all_days",
    }

    # Re-run overwrites same file (sync)
    write_usage_report(records, chinese=False)
    text2 = out.read_text(encoding="utf-8")
    assert "gai Token Usage Report" in text2


def test_trend_today_is_hourly_until_now() -> None:
    now = datetime.fromisoformat("2026-10-07T14:30:00+08:00")
    records = [
        UsageRecord(
            ts="2026-10-07T09:10:00+08:00",
            git_user="A",
            git_email="a@x.com",
            provider="deepseek",
            provider_name="DeepSeek",
            model="m",
            action="review",
            total_tokens=10,
        ),
        UsageRecord(
            ts="2026-10-07T14:05:00+08:00",
            git_user="A",
            git_email="a@x.com",
            provider="deepseek",
            provider_name="DeepSeek",
            model="m",
            action="review",
            total_tokens=20,
        ),
        UsageRecord(
            ts="2026-10-06T23:00:00+08:00",
            git_user="A",
            git_email="a@x.com",
            provider="deepseek",
            provider_name="DeepSeek",
            model="m",
            action="review",
            total_tokens=99,
        ),
    ]
    trends = build_trend_series(records, now=now)
    today = trends["today"]
    assert today["labels"][0] == "00:00"
    assert today["labels"][-1] == "14:00"
    assert len(today["labels"]) == 15
    assert today["tokens"][9] == 10
    assert today["tokens"][14] == 20
    assert sum(today["tokens"]) == 30

    last7 = trends["last7"]
    assert len(last7["labels"]) == 7
    assert last7["labels"][-1] == "2026-10-07"
    assert last7["tokens"][-1] == 30
    assert "2026-10" in trends["month"]["labels"]


def test_sync_usage_data_file_creates_html_shell(tmp_path: Path, monkeypatch) -> None:
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
            action="review",
            total_tokens=10,
            ok=True,
        ),
        path=log,
    )
    html = tmp_path / ".gai" / "usage-report.html"
    data = tmp_path / ".gai" / "usage-data.js"
    assert data.is_file()
    assert html.is_file()
    assert "echarts" in html.read_text(encoding="utf-8").lower()
    # Force sync still works
    assert sync_usage_data_file(log_path=log, force=True) == data
