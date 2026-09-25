"""Tests for friendly error formatting and period validation."""

from datetime import date

import pytest

from gai.errors import PeriodError, format_cli_error
from gai.git_ops import GitError, choose_remote, classify_remote_failure
from gai.llm.client import LLMError, classify_http_error
from gai.report import validate_report_period


def test_classify_http_unauthorized():
    assert classify_http_error(401, "invalid api key") == "unauthorized"


def test_classify_http_billing():
    assert classify_http_error(402, "") == "billing"
    assert classify_http_error(403, "insufficient_quota") == "billing"
    assert classify_http_error(400, "You exceeded your current quota") == "billing"


def test_classify_http_rate_limit():
    assert classify_http_error(429, "slow down") == "rate_limit"


def test_classify_http_server():
    assert classify_http_error(503, "busy") == "server"


def test_format_llm_billing_cn():
    exc = LLMError("raw", kind="billing", status_code=402, detail="quota")
    msg = format_cli_error(exc, chinese=True)
    assert "欠费" in msg or "配额" in msg


def test_format_llm_missing_key_cn():
    exc = LLMError("no key", kind="missing_key")
    assert "API Key" in format_cli_error(exc, chinese=True)


def test_format_git_no_remote_cn():
    with pytest.raises(GitError) as caught:
        choose_remote([])
    msg = format_cli_error(caught.value, chinese=True)
    assert "远程" in msg


def test_classify_remote_auth():
    assert classify_remote_failure("Permission denied (publickey)") == "auth"
    assert classify_remote_failure("! [rejected] non-fast-forward") == "rejected"
    assert classify_remote_failure("Could not resolve host: github.com") == "network"


def test_period_since_after_until():
    with pytest.raises(PeriodError) as caught:
        validate_report_period(
            since_query="2026-09-20",
            until_query="2026-09-01",
            today=date(2026, 9, 25),
        )
    assert caught.value.code == "since_after_until"
    msg = format_cli_error(caught.value, chinese=True)
    assert "晚于" in msg


def test_period_invalid_iso_since():
    with pytest.raises(PeriodError) as caught:
        validate_report_period(
            since_query="2026-13-40",
            until_query=None,
            today=date(2026, 9, 25),
        )
    assert caught.value.code == "invalid_since"
    en = format_cli_error(caught.value, chinese=False)
    cn = format_cli_error(caught.value, chinese=True)
    assert "YYYY-MM-DD" in en
    assert "7d" in en
    assert "正确格式" in cn
    assert "2026-09-01" in cn


def test_period_invalid_iso_until():
    with pytest.raises(PeriodError) as caught:
        validate_report_period(
            since_query="7d",
            until_query="2026-99-01",
            today=date(2026, 9, 25),
        )
    assert caught.value.code == "invalid_until"
    cn = format_cli_error(caught.value, chinese=True)
    assert "正确格式" in cn
    assert "YYYY-MM-DD" in cn


def test_period_relative_vs_until_ok():
    validate_report_period(
        since_query="7d",
        until_query="2026-09-25",
        today=date(2026, 9, 25),
    )


def test_period_relative_after_until():
    with pytest.raises(PeriodError) as caught:
        validate_report_period(
            since_query="7d",
            until_query="2026-09-10",
            today=date(2026, 9, 25),
        )
    assert caught.value.code == "since_after_until"


def test_period_alltime_skips_since_compare():
    validate_report_period(
        since_query="alltime",
        until_query="2026-09-01",
        alltime=True,
        today=date(2026, 9, 25),
    )
