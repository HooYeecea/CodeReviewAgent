"""Tests for LLM usage tracking and footer wording helpers."""

from gai.llm.usage import (
    clear_llm_usage,
    get_llm_calls,
    record_llm_call,
    usage_totals,
)


def test_usage_empty_after_clear():
    record_llm_call(model="gpt-test", prompt_tokens=10, completion_tokens=5, total_tokens=15)
    clear_llm_usage()
    assert get_llm_calls() == []
    assert usage_totals() == (None, None, None)


def test_usage_totals_sum_multiple_calls():
    clear_llm_usage()
    record_llm_call(model="m1", prompt_tokens=100, completion_tokens=20, total_tokens=120)
    record_llm_call(model="m1", prompt_tokens=50, completion_tokens=10, total_tokens=60)
    prompt, completion, total = usage_totals()
    assert prompt == 150
    assert completion == 30
    assert total == 180
    assert len(get_llm_calls()) == 2


def test_print_llm_usage_not_called(capsys):
    from gai.cli import _print_llm_usage

    clear_llm_usage()
    _print_llm_usage(chinese=True)
    out = capsys.readouterr().out
    assert "未涉及调用大模型" in out


def test_print_llm_usage_called_with_tokens(capsys):
    from gai.cli import _print_llm_usage

    clear_llm_usage()
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
