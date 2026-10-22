"""Compatibility shim — implementation lives in ``gai.history.commands``."""

from __future__ import annotations

from gai.history.commands import (
    CommandRecord,
    append_command_record,
    command_log_path,
    extract_command,
    format_command_table,
    history_enabled,
    load_command_records,
    maybe_record_command,
    sanitize_argv,
)

__all__ = [
    "CommandRecord",
    "append_command_record",
    "command_log_path",
    "extract_command",
    "format_command_table",
    "history_enabled",
    "load_command_records",
    "maybe_record_command",
    "sanitize_argv",
]
