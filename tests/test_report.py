"""Tests for report parsing, participants, and output path helpers."""

from pathlib import Path

from gai.git_ops import (
    CommitInfo,
    format_commits_for_prompt,
    is_alltime_token,
    resolve_since,
    _parse_commit_log,
)
from gai.report import (
    build_export_markdown,
    collect_participant_stats,
    parse_report_response,
    resolve_report_output_path,
)


def test_resolve_since_relative():
    assert resolve_since("7d") == "7 days ago"
    assert resolve_since("2w") == "2 weeks ago"
    assert resolve_since("1m") == "1 months ago"
    assert resolve_since("1y") == "1 years ago"


def test_resolve_since_absolute_passthrough():
    assert resolve_since("2026-09-01") == "2026-09-01"
    assert resolve_since("3 days ago") == "3 days ago"
    assert resolve_since(None) is None
    assert resolve_since("  ") is None


def test_resolve_since_alltime():
    assert resolve_since("alltime") is None
    assert resolve_since("all-time") is None
    assert resolve_since("ALL") is None
    assert is_alltime_token("alltime") is True
    assert is_alltime_token("7d") is False


def test_parse_commit_log_with_stat():
    raw = """
===GAI_COMMIT===
abc1234deadbeef
Alice
alice@example.com
2026-09-20
feat: add report command

 2 files changed, 40 insertions(+), 3 deletions(-)
===GAI_COMMIT===
def5678cafebabe
Bob
bob@example.com
2026-09-21
fix: handle empty log
"""
    commits = _parse_commit_log(raw)
    assert len(commits) == 2
    assert commits[0].subject == "feat: add report command"
    assert "2 files changed" in commits[0].shortstat
    assert commits[1].author_name == "Bob"
    assert commits[1].shortstat == ""


def test_format_commits_for_prompt_truncates():
    commits = [
        CommitInfo(
            hash="a" * 40,
            author_name="A",
            author_email="a@e.com",
            date="2026-09-01",
            subject="x" * 100,
        )
    ]
    text, truncated = format_commits_for_prompt(commits, max_chars=50)
    assert truncated is True
    assert "truncated" in text


def test_collect_participant_stats():
    commits = [
        CommitInfo("h1", "Alice", "a@e.com", "2026-09-01", "feat: a"),
        CommitInfo("h2", "Alice", "a@e.com", "2026-09-02", "fix: b"),
        CommitInfo("h3", "Bob", "b@e.com", "2026-09-03", "chore: c"),
    ]
    stats = collect_participant_stats(commits)
    assert len(stats) == 2
    assert stats[0].name == "Alice"
    assert stats[0].commit_count == 2
    assert stats[0].share == 66.7
    assert stats[1].name == "Bob"
    assert stats[1].commit_count == 1


def test_parse_report_response_ok():
    raw = """
    {
      "period_summary": "Shipped report CLI",
      "highlights": ["Added gai report"],
      "categories": [
        {"name": "Features", "items": ["Work report from git log"]}
      ],
      "participants": [
        {"name": "Alice", "email": "a@e.com", "commit_count": 2, "summary": "built report"}
      ],
      "per_author": [
        {"name": "Alice", "email": "a@e.com", "highlights": ["report"], "items": ["CLI"]}
      ],
      "contributor_count": 1,
      "report_markdown": "## Done\\n- report",
      "commit_count": 3
    }
    """
    result = parse_report_response(raw)
    assert result.parsed_ok is True
    assert result.period_summary.startswith("Shipped")
    assert result.highlights == ["Added gai report"]
    assert result.categories[0].name == "Features"
    assert result.commit_count == 3
    assert result.participants[0].summary == "built report"
    assert result.per_author[0].highlights == ["report"]


def test_parse_report_response_fallback():
    raw = "not json at all, just a paragraph about work"
    result = parse_report_response(raw)
    assert result.parsed_ok is False
    assert "paragraph" in result.report_markdown


def test_resolve_report_output_path_filename(tmp_path: Path):
    target, warning = resolve_report_output_path("week.md", cwd=tmp_path)
    assert warning is None
    assert target == (tmp_path / "week.md").resolve()


def test_resolve_report_output_path_missing_parent_fallback(tmp_path: Path):
    bad = tmp_path / "nope" / "nested" / "week.md"
    target, warning = resolve_report_output_path(str(bad), cwd=tmp_path)
    assert warning is not None
    assert "not found" in warning.lower() or "Directory" in warning
    assert target == (tmp_path / "week.md").resolve()


def test_resolve_report_output_path_directory(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    target, warning = resolve_report_output_path(str(reports), cwd=tmp_path)
    assert warning is None
    assert target.parent == reports.resolve()
    assert target.name.startswith("gai-report-")
    assert target.suffix == ".md"


def test_build_export_markdown_includes_participants():
    from gai.report import ParticipantStat, ReportResult

    result = ReportResult(
        period_summary="did stuff",
        team_mode=True,
        contributor_count=1,
        commit_count=2,
        participants=[
            ParticipantStat("Alice", "a@e.com", 2, 100.0, "built feature"),
        ],
        report_markdown="## body",
    )
    md = build_export_markdown(result, chinese=True)
    assert "参与者" in md
    assert "Alice" in md
    assert "built feature" in md
