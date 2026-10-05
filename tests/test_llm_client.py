"""Tests for LLM HTTP retry behavior."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from gai.config import Settings
from gai.llm.client import LLMClient, LLMError
from gai.llm.usage import clear_llm_usage, get_llm_calls


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
    assert get_llm_calls() == []
    assert len(client._slept) == 2  # type: ignore[attr-defined]


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
