"""gai report — work summary from git commits."""

from __future__ import annotations

from gai.report.work import (
    ParticipantStat,
    PerAuthorSection,
    ReportCategory,
    ReportResult,
    build_export_markdown,
    collect_participant_stats,
    compute_period_bounds,
    export_report,
    parse_report_response,
    render_report,
    resolve_report_output_path,
    run_report,
    validate_report_period,
)

__all__ = [
    "ParticipantStat",
    "PerAuthorSection",
    "ReportCategory",
    "ReportResult",
    "build_export_markdown",
    "collect_participant_stats",
    "compute_period_bounds",
    "export_report",
    "parse_report_response",
    "render_report",
    "resolve_report_output_path",
    "run_report",
    "validate_report_period",
]
