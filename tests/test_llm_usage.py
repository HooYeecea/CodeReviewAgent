"""Tests for LLM usage tracking and footer wording helpers."""

from gai.common.llm.usage import (
    clear_llm_usage,
    get_llm_calls,
    record_llm_call,
    usage_totals,
    record_llm_failure,
    get_llm_failures,
)


def test_usage_empty_after_clear():
    record_llm_failure()
    record_llm_call(model="gpt-test", prompt_tokens=10, completion_tokens=5, total_tokens=15)
    clear_llm_usage()
    assert get_llm_calls() == []
    assert get_llm_failures() == 0
    assert usage_totals() == (None, None, None)


def test_usage_totals_missing_total_not_estimated():
    clear_llm_usage()
    record_llm_call(model="m1", prompt_tokens=8, completion_tokens=2, total_tokens=None)
    prompt, completion, total = usage_totals()
    assert prompt == 8
    assert completion == 2
    assert total is None

    clear_llm_usage()
    record_llm_call(model="m1", prompt_tokens=100, completion_tokens=20, total_tokens=120)
    record_llm_call(model="m1", prompt_tokens=50, completion_tokens=10, total_tokens=60)
    prompt, completion, total = usage_totals()
    assert prompt == 150
    assert completion == 30
    assert total == 180
    assert len(get_llm_calls()) == 2


def test_print_llm_usage_not_called(capsys):
    from gai import cli_common as cli_mod
    from gai.cli_common import _print_llm_usage

    clear_llm_usage()
    cli_mod._LLM_USAGE_PRINTED = False
    _print_llm_usage(chinese=True)
    out = capsys.readouterr().out
    assert "未涉及调用大模型" in out
    # second call skipped (once=True)
    _print_llm_usage(chinese=True)
    out2 = capsys.readouterr().out
    assert out2 == ""


def test_print_llm_usage_called_with_tokens(capsys):
    from gai import cli_common as cli_mod
    from gai.cli_common import _print_llm_usage

    clear_llm_usage()
    cli_mod._LLM_USAGE_PRINTED = False
    record_llm_call(
        model="gpt-4o-mini",
        prompt_tokens=120,
        completion_tokens=40,
        total_tokens=160,
    )
    _print_llm_usage(chinese=True)
    out = capsys.readouterr().out
    assert "已调用大模型" in out
    assert "gpt-4o-mini" in out
    assert "160" in out


def test_failed_call_footer_does_not_claim_no_call(capsys):
    from gai.cli_common import _print_llm_usage
    clear_llm_usage()
    record_llm_failure()
    _print_llm_usage(chinese=True, once=False)
    output = capsys.readouterr().out
    assert "调用失败" in output
    assert "未涉及调用" not in output
    assert "用量未知" in output
    _print_llm_usage(chinese=False, once=False)
    assert "failed" in capsys.readouterr().out


def test_mixed_footer_separates_successful_token_usage(capsys):
    from gai.cli_common import _print_llm_usage
    clear_llm_usage()
    record_llm_failure()
    record_llm_call(model="test", prompt_tokens=3, completion_tokens=2, total_tokens=5)
    _print_llm_usage(chinese=True, once=False)
    output = capsys.readouterr().out
    assert "调用失败" in output
    assert "以下仅统计成功调用" in output
    assert "消耗 token 5" in output
