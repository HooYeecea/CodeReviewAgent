"""Compatibility shim — implementation lives in ``gai.reports.guide``."""

from __future__ import annotations

from gai.reports.guide import guide_path, path_to_file_url, write_guide_html

__all__ = [
    "guide_path",
    "path_to_file_url",
    "write_guide_html",
]
