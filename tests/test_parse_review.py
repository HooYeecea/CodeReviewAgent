"""Tests for review response parsing and degradation."""

import json
from io import StringIO

import pytest
from rich.console import Console

from gai.review import parse_review_response, render_review


def test_parse_clean_json():
    raw = """
    {
      "review": [
        {
          "severity": "warning",
          "file": "app.py",
          "line": 42,
          "issue": "Possible N+1 query",
          "suggestion": "Batch the lookups"
        }
      ],
      "commit_message": "perf(db): batch user lookups",
      "summary": "Optimizes database access"
    }
    """
    result = parse_review_response(raw)
    assert result.parsed_ok is True
    assert result.commit_message == "perf(db): batch user lookups"
    assert result.summary.startswith("Optimizes")
    assert len(result.review) == 1
    item = result.review[0]
    assert item.severity == "warning"
    assert item.file == "app.py"
    assert item.line == 42
    assert "N+1" in item.issue


def test_parse_json_in_fence():
    raw = """Here you go:
```json
{"review": [], "commit_message": "chore: tidy imports", "summary": "cleanup"}
```
"""
    result = parse_review_response(raw)
    assert result.parsed_ok is True
    assert result.commit_message == "chore: tidy imports"
    assert result.review == []


def test_parse_severity_aliases():
    raw = '{"review":[{"severity":"error","file":"x.py","line":1,"issue":"bug","suggestion":"fix"}],"commit_message":"fix: bug"}'
    result = parse_review_response(raw)
    assert result.review[0].severity == "critical"


def test_parse_invalid_falls_back():
    raw = "Sorry, I cannot produce JSON right now. Maybe feat: something"
    result = parse_review_response(raw)
    assert result.parsed_ok is False
    assert result.commit_message == ""
    assert "cannot produce JSON" in result.summary
    assert result.raw_text == raw


def test_parse_rejects_empty_issues():
    raw = '{"review":[{"severity":"info","file":"a.py","line":null,"issue":"","suggestion":"x"}],"commit_message":"docs: update"}'
    result = parse_review_response(raw)
    assert result.parsed_ok is False
    assert result.review == []
    assert result.commit_message == ""


def test_to_dict_shape():
    raw = '{"review":[],"commit_message":"feat: x","summary":"y"}'
    result = parse_review_response(raw)
    data = result.to_dict()
    assert data["commit_message"] == "feat: x"
    assert data["parsed_ok"] is True
    assert isinstance(data["review"], list)
    assert data["status"] == "passed"


@pytest.mark.parametrize("payload", [
    {}, {"commit_message": "fix: x"},
    {"review": None, "commit_message": "fix: x"},
    {"review": "invalid", "commit_message": "fix: x"},
    {"review": [], "commit_message": 42},
    {"review": [], "commit_message": "fix: x", "summary": {}},
    {"review": ["bug"], "commit_message": "fix: x"},
    {"review": [{"file": "a.py", "severity": "unknown", "issue": "bug"}], "commit_message": "fix: x"},
    {"review": [{"file": "a.py", "severity": "warning", "issue": "bug", "line": True}], "commit_message": "fix: x"},
])
def test_invalid_schema_never_reports_clean(payload):
    result = parse_review_response(json.dumps(payload))
    assert result.to_dict()["status"] == "failed"
    output = StringIO()
    render_review(result, Console(file=output, color_system=None))
    assert "No issues found" not in output.getvalue()


def test_valid_findings_have_issues_status():
    result = parse_review_response(json.dumps({
        "review": [{"file": "a.py", "severity": "critical", "issue": "bug", "line": None}],
        "commit_message": "fix: bug",
    }))
    assert result.to_dict()["status"] == "issues"
