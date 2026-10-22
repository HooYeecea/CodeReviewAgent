"""Compatibility shim — implementation lives in ``gai.history.report``."""

from __future__ import annotations

from gai.history.report import (
    build_history_analytics,
    build_history_datasets,
    history_data_path,
    history_report_path,
    path_to_file_url,
    render_history_report_html,
    sync_history_data_file,
    write_history_data_js,
    write_history_report,
)

__all__ = [
    "build_history_analytics",
    "build_history_datasets",
    "history_data_path",
    "history_report_path",
    "path_to_file_url",
    "render_history_report_html",
    "sync_history_data_file",
    "write_history_data_js",
    "write_history_report",
]
