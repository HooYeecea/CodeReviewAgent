"""Tests for HTML command history report generation."""

from __future__ import annotations

from pathlib import Path

from gai.command_history import CommandRecord, append_command_record, load_command_records
from gai.history_report import (
    build_history_datasets,
    history_report_path,
    path_to_file_url,
    sync_history_data_file,
    write_history_report,
)


def test_write_history_report_fixed_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("gai.history_report.project_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr("gai.command_history.project_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr("gai.llm.history.project_root", lambda cwd=None: tmp_path)

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
            repo_name="CodeReviewAgent",
            remote_name="origin",
        ),
        path=log,
    )
    append_command_record(
        CommandRecord(
            ts="2026-10-08T11:00:00+08:00",
            command="push",
            argv=["push", "--cn"],
            exit_code=1,
            ok=False,
            duration_ms=40,
            git_user="Bob",
            git_email="b@x.com",
            repo_name="OtherApp",
            remote_name=None,
        ),
        path=log,
    )

    records = load_command_records(path=log)
    out = write_history_report(records, chinese=True)
    assert out == tmp_path / ".gai" / "history-report.html"
    assert out == history_report_path()
    text = out.read_text(encoding="utf-8")
    data_js = (tmp_path / ".gai" / "history-data.js").read_text(encoding="utf-8")
    assert "gai 命令执行报告" in text
    assert "echarts" in text.lower()
    assert "btn-refresh" in text
    assert "btn-export-csv" in text
    assert "btn-theme-dark" in text
    assert "btn-lang-cn" in text
    assert "gai-ui-theme" in text
    assert "gai-ui-lang" in text
    assert "history-data.js" in text
    assert "project-dd" in text
    assert "scope-all" in text
    assert "chart-heat-repo" in text
    assert "window.__GAI_HISTORY_DATASETS__" in data_js
    assert "commit" in data_js
    url = path_to_file_url(out)
    assert url.startswith("file://")

    datasets = build_history_datasets(records)
    assert datasets["default_project"] == "__all__"
    assert {p["id"] for p in datasets["projects"]} == {"CodeReviewAgent", "OtherApp"}
    assert datasets["all"]["totals"]["calls"] == 2
    assert datasets["all"]["totals"]["ok"] == 1
    assert datasets["all"]["totals"]["fail"] == 1
    assert datasets["by_project"]["CodeReviewAgent"]["totals"]["calls"] == 1

    write_history_report(records, chinese=False)
    assert "gai Command History Report" in out.read_text(encoding="utf-8")


def test_sync_history_creates_html_shell(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("gai.history_report.project_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr("gai.command_history.project_root", lambda cwd=None: tmp_path)
    log = tmp_path / ".gai" / "commands.jsonl"
    append_command_record(
        CommandRecord(
            ts="2026-10-07T10:00:00+08:00",
            command="guide",
            argv=["guide", "--cn"],
            exit_code=0,
            ok=True,
            duration_ms=10,
            repo_name="Demo",
        ),
        path=log,
    )
    html = tmp_path / ".gai" / "history-report.html"
    data = tmp_path / ".gai" / "history-data.js"
    assert data.is_file()
    assert html.is_file()
    assert sync_history_data_file(log_path=log, force=True) == data
