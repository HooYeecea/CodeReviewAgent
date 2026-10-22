"""Local / global JSONL history stores (commands + path helpers)."""

from __future__ import annotations

from gai.history.commands import (
    CommandRecord,
    append_command_record,
    command_log_path,
    load_command_records,
    maybe_record_command,
)
from gai.history.store import (
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
)

__all__ = [
    "CommandRecord",
    "append_command_record",
    "command_log_path",
    "ensure_global_logs_merged",
    "global_command_log_path",
    "global_gai_dir",
    "global_history_report_path",
    "global_usage_log_path",
    "global_usage_report_path",
    "load_command_records",
    "local_command_log_path",
    "local_gai_dir",
    "local_history_report_path",
    "local_usage_log_path",
    "local_usage_report_path",
    "maybe_record_command",
]
