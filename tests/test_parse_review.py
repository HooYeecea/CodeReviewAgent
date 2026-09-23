"""Tests for review response parsing and degradation."""

from gai.review import parse_review_response


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


def test_parse_skips_empty_issues():
    raw = '{"review":[{"severity":"info","file":"a.py","line":null,"issue":"","suggestion":"x"}],"commit_message":"docs: update"}'
    result = parse_review_response(raw)
    assert result.parsed_ok is True
    assert result.review == []
    assert result.commit_message == "docs: update"


def test_to_dict_shape():
    raw = '{"review":[],"commit_message":"feat: x","summary":"y"}'
    result = parse_review_response(raw)
    data = result.to_dict()
    assert data["commit_message"] == "feat: x"
    assert data["parsed_ok"] is True
    assert isinstance(data["review"], list)
