"""Query provider account balance when the vendor exposes an API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from gai.config import Settings
from gai.llm.client import LLMError, classify_http_error


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name_en: str
    name_cn: str
    supports_balance: bool


@dataclass
class BalanceItem:
    """One balance row (currency / total / extras)."""

    currency: str | None = None
    total: str | None = None
    granted: str | None = None
    topped_up: str | None = None
    charge: str | None = None
    gift: str | None = None


@dataclass
class BalanceResult:
    supported: bool
    provider: ProviderInfo
    model: str
    available: bool | None = None
    items: list[BalanceItem] = field(default_factory=list)


def detect_provider(base_url: str) -> ProviderInfo:
    """Infer vendor from configured base_url host."""
    host = (urlparse(base_url).netloc or base_url).lower()
    if "deepseek" in host:
        return ProviderInfo("deepseek", "DeepSeek", "DeepSeek", True)
    if "siliconflow" in host:
        return ProviderInfo("siliconflow", "SiliconFlow", "硅基流动", True)
    if "openai.com" in host:
        return ProviderInfo("openai", "OpenAI", "OpenAI", False)
    if "openrouter" in host:
        return ProviderInfo("openrouter", "OpenRouter", "OpenRouter", False)
    if "dashscope" in host or "aliyuncs.com" in host:
        return ProviderInfo("dashscope", "Alibaba DashScope", "通义 / 阿里云百炼", False)
    if "moonshot" in host:
        return ProviderInfo("moonshot", "Moonshot", "月之暗面 Moonshot", False)
    return ProviderInfo("unknown", "Unknown provider", "未知厂商", False)


def _origin_root(base_url: str) -> str:
    """https://api.deepseek.com/v1 -> https://api.deepseek.com"""
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return base_url.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_balance(settings: Settings) -> BalanceResult:
    """Query balance. Requires API key; unsupported providers return supported=False."""
    if not settings.api_key:
        raise LLMError(
            "API key not configured. Set GAI_API_KEY / OPENAI_API_KEY "
            "or run: gai config --api-key <key>",
            kind="missing_key",
        )

    provider = detect_provider(settings.base_url)
    if not provider.supports_balance:
        return BalanceResult(
            supported=False,
            provider=provider,
            model=settings.model,
        )
    if provider.id == "deepseek":
        return _query_deepseek(settings, provider)
    if provider.id == "siliconflow":
        return _query_siliconflow(settings, provider)
    return BalanceResult(supported=False, provider=provider, model=settings.model)


def _get_json(url: str, *, api_key: str, timeout: float) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMError(
            f"Balance request timed out after {timeout}s",
            kind="timeout",
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Balance request failed: {exc}",
            kind="network",
            detail=str(exc),
        ) from exc

    if response.status_code >= 400:
        detail = (response.text or "")[:500]
        kind = classify_http_error(response.status_code, detail)
        raise LLMError(
            f"Balance API error {response.status_code}: {detail}",
            kind=kind,
            status_code=response.status_code,
            detail=detail,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError(
            "Unexpected balance response shape",
            kind="bad_response",
            detail=str(exc),
        ) from exc
    if not isinstance(data, dict):
        raise LLMError(
            "Unexpected balance response shape",
            kind="bad_response",
            detail=f"expected object, got {type(data).__name__}",
        )
    return data


def _query_deepseek(settings: Settings, provider: ProviderInfo) -> BalanceResult:
    # Docs: GET https://api.deepseek.com/user/balance (not under /v1)
    url = f"{_origin_root(settings.base_url)}/user/balance"
    data = _get_json(url, api_key=settings.api_key, timeout=settings.timeout)
    items: list[BalanceItem] = []
    for row in data.get("balance_infos") or []:
        if not isinstance(row, dict):
            continue
        items.append(
            BalanceItem(
                currency=str(row.get("currency") or "") or None,
                total=_str_or_none(row.get("total_balance")),
                granted=_str_or_none(row.get("granted_balance")),
                topped_up=_str_or_none(row.get("topped_up_balance")),
            )
        )
    available = data.get("is_available")
    return BalanceResult(
        supported=True,
        provider=provider,
        model=settings.model,
        available=bool(available) if available is not None else None,
        items=items,
    )


def _query_siliconflow(settings: Settings, provider: ProviderInfo) -> BalanceResult:
    # Docs: GET https://api.siliconflow.cn/v1/user/info
    url = f"{settings.base_url.rstrip('/')}/user/info"
    data = _get_json(url, api_key=settings.api_key, timeout=settings.timeout)
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        raise LLMError(
            "Unexpected balance response shape",
            kind="bad_response",
            detail="missing data object",
        )
    item = BalanceItem(
        currency="CNY",
        total=_str_or_none(payload.get("totalBalance") or payload.get("total_balance")),
        gift=_str_or_none(payload.get("balance")),
        charge=_str_or_none(payload.get("chargeBalance") or payload.get("charge_balance")),
    )
    return BalanceResult(
        supported=True,
        provider=provider,
        model=settings.model,
        items=[item],
    )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_balance_result(result: BalanceResult, *, chinese: bool = False) -> str:
    """Human-readable balance output."""
    provider = result.provider.name_cn if chinese else result.provider.name_en
    model = result.model

    if not result.supported:
        if chinese:
            return (
                f"当前厂商：{provider}\n"
                f"当前模型：{model}\n"
                f"该厂商未提供可用的余额查询接口，gai 暂不支持查询余额。\n"
                f"请到该厂商控制台查看账单 / 额度。"
            )
        return (
            f"Provider: {provider}\n"
            f"Model: {model}\n"
            f"This provider does not expose a balance API that gai supports.\n"
            f"Check billing/credits in the provider console."
        )

    lines: list[str] = []
    if chinese:
        lines.append(f"厂商：{provider}")
        lines.append(f"模型：{model}")
        if result.available is not None:
            lines.append(
                "余额状态：可用（足够发起调用）"
                if result.available
                else "余额状态：不足 / 不可用"
            )
        if not result.items:
            lines.append("未返回明细余额。")
        for item in result.items:
            currency = item.currency or ""
            unit = f" {currency}" if currency else ""
            if item.total is not None:
                lines.append(f"可用总额：{item.total}{unit}")
            if item.topped_up is not None:
                lines.append(f"充值余额：{item.topped_up}{unit}")
            if item.granted is not None:
                lines.append(f"赠送余额：{item.granted}{unit}")
            if item.charge is not None:
                lines.append(f"充值余额：{item.charge}{unit}")
            if item.gift is not None and item.granted is None:
                lines.append(f"赠送余额：{item.gift}{unit}")
    else:
        lines.append(f"Provider: {provider}")
        lines.append(f"Model: {model}")
        if result.available is not None:
            lines.append(
                "Status: available for API calls"
                if result.available
                else "Status: insufficient / unavailable"
            )
        if not result.items:
            lines.append("No detailed balance rows returned.")
        for item in result.items:
            currency = item.currency or ""
            unit = f" {currency}" if currency else ""
            if item.total is not None:
                lines.append(f"Total balance: {item.total}{unit}")
            if item.topped_up is not None:
                lines.append(f"Topped-up: {item.topped_up}{unit}")
            if item.granted is not None:
                lines.append(f"Granted: {item.granted}{unit}")
            if item.charge is not None:
                lines.append(f"Charged: {item.charge}{unit}")
            if item.gift is not None and item.granted is None:
                lines.append(f"Gift balance: {item.gift}{unit}")
    return "\n".join(lines)
