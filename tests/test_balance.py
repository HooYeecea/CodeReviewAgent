"""Tests for provider balance detection and formatting."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from gai.config import Settings
from gai.llm.balance import (
    detect_provider,
    fetch_balance,
    format_balance_result,
)
from gai.llm.client import LLMError


def test_detect_deepseek_and_siliconflow():
    assert detect_provider("https://api.deepseek.com/v1").id == "deepseek"
    assert detect_provider("https://api.deepseek.com/v1").supports_balance is True
    assert detect_provider("https://api.siliconflow.cn/v1").id == "siliconflow"
    assert detect_provider("https://api.openai.com/v1").supports_balance is False


def test_missing_api_key_raises():
    settings = Settings(api_key="", base_url="https://api.deepseek.com/v1", model="deepseek-chat")
    with pytest.raises(LLMError) as caught:
        fetch_balance(settings)
    assert caught.value.kind == "missing_key"


def test_unsupported_provider_message_cn():
    settings = Settings(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    result = fetch_balance(settings)
    assert result.supported is False
    text = format_balance_result(result, chinese=True)
    assert "OpenAI" in text
    assert "gpt-4o-mini" in text
    assert "不支持查询余额" in text


def test_deepseek_balance_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "12.34",
                "granted_balance": "2.00",
                "topped_up_balance": "10.34",
            }
        ],
    }

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, Any]:
            return payload

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
            assert url == "https://api.deepseek.com/user/balance"
            assert headers and "Authorization" in headers
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    settings = Settings(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    result = fetch_balance(settings)
    assert result.supported is True
    assert result.available is True
    assert result.items[0].total == "12.34"
    text = format_balance_result(result, chinese=True)
    assert "12.34" in text
    assert "DeepSeek" in text


def test_siliconflow_balance_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "code": 20000,
        "data": {
            "totalBalance": "88.00",
            "balance": "8.00",
            "chargeBalance": "80.00",
        },
    }

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, Any]:
            return payload

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
            assert url.endswith("/v1/user/info")
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    settings = Settings(
        api_key="sk-test",
        base_url="https://api.siliconflow.cn/v1",
        model="Qwen/Qwen2.5-7B-Instruct",
    )
    result = fetch_balance(settings)
    assert result.supported is True
    assert result.items[0].total == "88.00"
    text = format_balance_result(result, chinese=True)
    assert "硅基流动" in text
    assert "88.00" in text
