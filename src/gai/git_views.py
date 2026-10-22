"""Compatibility shim — implementation lives in ``gai.git.views``."""

from __future__ import annotations

from gai.git.views import (
    _display_width,
    log_report_path,
    path_to_file_url,
    render_pretty_log,
    render_pretty_status,
    write_log_report,
)

__all__ = [
    "_display_width",
    "log_report_path",
    "path_to_file_url",
    "render_pretty_log",
    "render_pretty_status",
    "write_log_report",
]
