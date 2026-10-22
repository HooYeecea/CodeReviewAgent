"""Compatibility shim — implementation lives in ``gai.reports.graph``."""

from __future__ import annotations

from gai.reports.graph import (  # noqa: F401
    graph_data_path,
    graph_report_path,
    path_to_file_url,
    write_graph_report,
)

__all__ = [
    "graph_data_path",
    "graph_report_path",
    "path_to_file_url",
    "write_graph_report",
]
