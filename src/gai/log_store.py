"""Compatibility shim — implementation lives in ``gai.history.store``."""

from __future__ import annotations

from gai.common.config import CONFIG_DIR
from gai.history.store import (
    cleanup_global_logs,
    discover_sibling_project_logs,
    ensure_global_logs_merged,
    global_command_log_path,
    global_gai_dir,
    global_history_report_path,
    global_usage_log_path,
    global_usage_report_path,
    local_command_log_path,
    local_gai_dir,
    local_history_report_path,
    local_usage_log_path,
    local_usage_report_path,
    merge_jsonl_into,
)
from gai.common.llm.history import project_root

__all__ = [
    "cleanup_global_logs",
    "discover_sibling_project_logs",
    "ensure_global_logs_merged",
    "global_command_log_path",
    "global_gai_dir",
    "global_history_report_path",
    "global_usage_log_path",
    "global_usage_report_path",
    "local_command_log_path",
    "local_gai_dir",
    "local_history_report_path",
    "local_usage_log_path",
    "local_usage_report_path",
    "merge_jsonl_into",
]
