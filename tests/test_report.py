"""Tests for report parsing and since-date helpers."""

from gai.git_ops import (
    CommitInfo,
    format_commits_for_prompt,
    is_alltime_token,
    resolve_since,
    _parse_commit_log,
)
from gai.report import parse_report_response


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


def test_parse_report_response_ok():
    raw = """
    {
      "period_summary": "Shipped report CLI",
      "highlights": ["Added gai report"],
      "categories": [
        {"name": "Features", "items": ["Work report from git log"]}
      ],
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


def test_parse_report_response_fallback():
    raw = "not json at all, just a paragraph about work"
    result = parse_report_response(raw)
    assert result.parsed_ok is False
    assert "paragraph" in result.report_markdown
