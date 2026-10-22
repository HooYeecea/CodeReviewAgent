"""Compatibility shim — use ``gai.common.config``."""

from __future__ import annotations

from gai.common.config import *  # noqa: F403
from gai.common.config import (  # noqa: F401
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_DIFF_CHARS,
    DEFAULT_MODEL,
    DEFAULT_PROFILE,
    DEFAULT_TIMEOUT,
    ProfileInfo,
    Settings,
    format_profile_label,
    format_profiles_overview,
    get_active_profile_name,
    list_profiles,
    load_settings,
    mask_secret,
    profiles_summary,
    save_settings,
    settings_from_profile,
    settings_summary,
)
