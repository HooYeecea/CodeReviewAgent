"""Tests for LLM HTTP retry behavior."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from gai.common.config import Settings
from gai.common.llm.client import LLMClient, LLMError
from gai.common.llm.usage import clear_llm_usage, get_llm_calls, get_llm_failures


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _ok_payload() -> dict[str, Any]:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", "function_call", None, "unknown"])
def test_incomplete_finish_reason_rejected_even_with_valid_json(monkeypatch, reason):
    payload = _ok_payload()
    payload["choices"][0] = {"finish_reason": reason, "message": {
        "content": '{"review":[],"summary":"ok","commit_message":"fix: update"}'}}
    client = _client(monkeypatch, [_FakeResponse(200, payload=payload)])
    with pytest.raises(LLMError) as caught:
        client.chat(system="s", user="u")
    assert caught.value.kind == "incomplete_response"
    assert client._slept == []


def test_normal_stop_is_accepted(monkeypatch):
    payload = _ok_payload()
    payload["choices"][0]["finish_reason"] = "stop"
    assert _client(monkeypatch, [_FakeResponse(200, payload=payload)]).chat(system="s", user="u") == "hello"


@pytest.mark.parametrize('url,model,mode,expected', [
    ('https://api.deepseek.com', 'deepseek-flash', 'disabled', {'type': 'disabled'}),
    ('https://api.deepseek.com/v1', 'deepseek-flash', 'enabled', {'type': 'enabled'}),
    ('https://api.deepseek.com', 'deepseek-reasoner', 'disabled', None),
    ('https://api.deepseek.com', 'deepseek-chat', 'disabled', None),
    ('https://other.test/v1', 'deepseek-flash', 'disabled', None),
    ('https://api.deepseek.com.other.test', 'deepseek-flash', 'disabled', None),
])
def test_thinking_parameter_is_explicit_and_provider_scoped(monkeypatch, url, model, mode, expected):
    client = _client(monkeypatch, [_FakeResponse(200, payload=_ok_payload())])
    client.settings.base_url = url
    client.settings.model = model
    client.settings.deepseek_thinking = mode
    post = httpx.Client.post
    sent = []
    def capture(self, *args, **kwargs):
        sent.append(kwargs['json'])
        return post(self, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, 'post', capture)
    assert client.chat(system='s', user='u') == 'hello'
    assert sent[0].get('thinking') == expected
    assert sent[0]['messages'] == [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]


def _client(monkeypatch: pytest.MonkeyPatch, responses: list[_FakeResponse]) -> LLMClient:
    queue = list(responses)

    class _FakeHttp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _FakeHttp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            if not queue:
                raise AssertionError("unexpected extra HTTP call")
            return queue.pop(0)

    monkeypatch.setattr(httpx, "Client", _FakeHttp)
    settings = Settings(api_key="sk-test", model="gpt-test", timeout=5.0)
    slept: list[float] = []
    client = LLMClient(settings, sleep=slept.append)
    client._slept = slept  # type: ignore[attr-defined]
    return client


def test_retry_then_success_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_usage()
    client = _client(
        monkeypatch,
        [
            _FakeResponse(429, text="rate limit", headers={"Retry-After": "0"}),
            _FakeResponse(200, payload=_ok_payload()),
        ],
    )
    assert client.chat(system="s", user="u") == "hello"
    assert len(get_llm_calls()) == 1
    assert get_llm_failures() == 0
    assert client._slept == [0.0]  # type: ignore[attr-defined]


def test_retry_exhausted_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_usage()
    client = _client(
        monkeypatch,
        [
            _FakeResponse(500, text="boom"),
            _FakeResponse(502, text="bad gateway"),
            _FakeResponse(503, text="busy"),
        ],
    )
    with pytest.raises(LLMError) as caught:
        client.chat(system="s", user="u")
    assert caught.value.kind == "server"
    assert caught.value.status_code == 503
    assert caught.value.attempts == 3
    assert get_llm_failures() == 1
    assert get_llm_calls() == []
    assert len(client._slept) == 2  # type: ignore[attr-defined]


def test_provider_identifiers_and_key_redaction(monkeypatch):
    response = _FakeResponse(500, text='{"error":{"message":"key sk-test [red]failed[/red]"}}',
                             payload={'error': {'code': 'internal_server_error'}},
                             headers={'x-request-id': 'request-123'})
    client = _client(monkeypatch, [response, response, response])
    with pytest.raises(LLMError) as caught:
        client.chat(system='s', user='u')
    error = caught.value
    assert error.provider_code == 'internal_server_error'
    assert error.request_id == 'request-123'
    assert error.attempts == 3
    assert 'sk-test' not in str(error) + error.detail
    from gai.common.errors import format_cli_error
    text = format_cli_error(error, chinese=True)
    assert 'request-123' in text and 'internal_server_error' in text
    assert '3' in text and '--trace' in text


@pytest.mark.parametrize('value', ['sk-test', '<script>', 'bad\nidentifier', 'x' * 161, {'code': 'bad'}])
def test_untrusted_provider_identifiers_omitted(monkeypatch, value):
    response = _FakeResponse(400, text='invalid', payload={'error': {'code': value}},
                             headers={'x-request-id': value})
    client = _client(monkeypatch, [response])
    with pytest.raises(LLMError) as caught:
        client.chat(system='s', user='u')
    assert caught.value.provider_code == ''
    assert caught.value.request_id == ''


def test_no_retry_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_usage()
    client = _client(
        monkeypatch,
        [_FakeResponse(401, text="invalid key")],
    )
    with pytest.raises(LLMError) as caught:
        client.chat(system="s", user="u")
    assert caught.value.kind == "unauthorized"
    assert client._slept == []  # type: ignore[attr-defined]


def test_retry_timeout_then_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_usage()
    queue: list[object] = ["timeout", _FakeResponse(200, payload=_ok_payload())]

    class _FakeHttp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _FakeHttp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            item = queue.pop(0)
            if item == "timeout":
                raise httpx.TimeoutException("slow")
            assert isinstance(item, _FakeResponse)
            return item

    monkeypatch.setattr(httpx, "Client", _FakeHttp)
    settings = Settings(api_key="sk-test", model="gpt-test", timeout=1.0)
    client = LLMClient(settings, sleep=lambda _s: None)
    assert client.chat(system="s", user="u") == "hello"
