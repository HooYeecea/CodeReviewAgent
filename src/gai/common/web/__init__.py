"""Shared browser/HTML helpers for gai reports."""

from __future__ import annotations

from gai.common.web.prefs import PREF_LANG, PREF_THEME, early_prefs_script
from gai.common.web.serve import open_path, serve_gai_page
from gai.common.web.urls import path_to_file_url

__all__ = [
    "PREF_LANG",
    "PREF_THEME",
    "early_prefs_script",
    "open_path",
    "path_to_file_url",
    "serve_gai_page",
]
