"""Query provider account balance when the vendor exposes an API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
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
    usage: str | None = None
    remaining: str | None = None
    cash: str | None = None
    voucher: str | None = None


@dataclass
class BalanceResult:
    supported: bool
    provider: ProviderInfo
    model: str
    available: bool | None = None
    items: list[BalanceItem] = field(default_factory=list)
    note_en: str | None = None
    note_cn: str | None = None


# Providers with a known public balance/credits API (extensible).
_SUPPORTED_PROVIDER_HINTS_EN = (
    "DeepSeek, SiliconFlow, Moonshot/Kimi, OpenRouter"
)
_SUPPORTED_PROVIDER_HINTS_CN = (
    "DeepSeek、硅基流动、Moonshot/Kimi、OpenRouter"
)


def detect_provider(base_url: str) -> ProviderInfo:
    """Infer vendor from configured base_url host."""
    host = (urlparse(base_url).netloc or base_url).lower()
    if "deepseek" in host:
        return ProviderInfo("deepseek", "DeepSeek", "DeepSeek", True)
    if "siliconflow" in host:
        return ProviderInfo("siliconflow", "SiliconFlow", "硅基流动", True)
    if "moonshot" in host or "kimi.com" in host or "kimi.ai" in host:
        return ProviderInfo("moonshot", "Moonshot / Kimi", "月之暗面 Moonshot / Kimi", True)
    if "openrouter" in host:
        return ProviderInfo("openrouter", "OpenRouter", "OpenRouter", True)
    if "openai.com" in host:
        return ProviderInfo("openai", "OpenAI", "OpenAI", False)
    if "dashscope" in host or "aliyuncs.com" in host:
        return ProviderInfo("dashscope", "Alibaba DashScope", "通义 / 阿里云百炼", False)
    if "bigmodel.cn" in host or "zhipuai" in host:
        return ProviderInfo("zhipu", "Zhipu AI", "智谱 AI", False)
    if "minimaxi" in host or "minimax" in host:
        return ProviderInfo("minimax", "MiniMax", "MiniMax", False)
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
    handler = _HANDLERS.get(provider.id)
    if not provider.supports_balance or handler is None:
        return BalanceResult(
            supported=False,
            provider=provider,
            model=settings.model,
        )
    return handler(settings, provider)


def _get_json(
    url: str,
    *,
    api_key: str,
    timeout: float,
    bearer: bool = True,
) -> dict[str, Any]:
    auth = f"Bearer {api_key}" if bearer else api_key
    headers = {
        "Authorization": auth,
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
        # OpenRouter credits often need a management key
        if response.status_code == 403 and "management" in detail.lower():
            raise LLMError(
                "OpenRouter credits API requires a management API key. "
                "Create one in the OpenRouter dashboard, or check credits there.",
                kind="forbidden",
                status_code=403,
                detail=detail,
            )
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
    # GET https://api.deepseek.com/user/balance
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
    # GET https://api.siliconflow.cn/v1/user/info
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


def _query_moonshot(settings: Settings, provider: ProviderInfo) -> BalanceResult:
    # GET https://api.moonshot.cn/v1/users/me/balance
    # (intl: api.moonshot.ai — same path; CNY vs USD by host)
    url = f"{settings.base_url.rstrip('/')}/users/me/balance"
    data = _get_json(url, api_key=settings.api_key, timeout=settings.timeout)
    code = data.get("code")
    if data.get("status") is False or (code is not None and code not in (0, "0")):
        raise LLMError(
            f"Moonshot balance API rejected the request: {data!r}"[:500],
            kind="api",
            detail=str(data)[:500],
        )
    payload = data.get("data")
    if not isinstance(payload, dict):
        raise LLMError(
            "Unexpected balance response shape",
            kind="bad_response",
            detail="missing data object",
        )
    host = (urlparse(settings.base_url).netloc or "").lower()
    currency = "USD" if "moonshot.ai" in host or "kimi.ai" in host else "CNY"
    available = _as_float(payload.get("available_balance"))
    item = BalanceItem(
        currency=currency,
        total=_str_or_none(payload.get("available_balance")),
        voucher=_str_or_none(payload.get("voucher_balance")),
        cash=_str_or_none(payload.get("cash_balance")),
    )
    return BalanceResult(
        supported=True,
        provider=provider,
        model=settings.model,
        available=None if available is None else available > 0,
        items=[item],
    )


def _query_openrouter(settings: Settings, provider: ProviderInfo) -> BalanceResult:
    # GET https://openrouter.ai/api/v1/credits
    # Remaining ≈ total_credits - total_usage (management key may be required)
    base = settings.base_url.rstrip("/")
    if base.endswith("/api/v1"):
        url = f"{base}/credits"
    else:
        url = f"{_origin_root(settings.base_url)}/api/v1/credits"
    data = _get_json(url, api_key=settings.api_key, timeout=settings.timeout)
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        raise LLMError(
            "Unexpected balance response shape",
            kind="bad_response",
            detail="missing data object",
        )
    total = _as_float(payload.get("total_credits") or payload.get("totalCredits"))
    usage = _as_float(payload.get("total_usage") or payload.get("totalUsage"))
    remaining = None
    if total is not None and usage is not None:
        remaining = max(total - usage, 0.0)
    item = BalanceItem(
        currency="credits",
        total=_fmt_num(total),
        usage=_fmt_num(usage),
        remaining=_fmt_num(remaining),
    )
    return BalanceResult(
        supported=True,
        provider=provider,
        model=settings.model,
        available=None if remaining is None else remaining > 0,
        items=[item],
        note_en="OpenRouter remaining ≈ purchased credits − usage.",
        note_cn="OpenRouter 剩余额度 ≈ 已购 credits − 已用 credits。",
    )


_HANDLERS: dict[str, Callable[[Settings, ProviderInfo], BalanceResult]] = {
    "deepseek": _query_deepseek,
    "siliconflow": _query_siliconflow,
    "moonshot": _query_moonshot,
    "openrouter": _query_openrouter,
}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: float | None) -> str | None:
    if value is None:
        return None
    # Trim trailing zeros for readability
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def format_balance_result(result: BalanceResult, *, chinese: bool = False) -> str:
    """Human-readable balance output."""
    provider = result.provider.name_cn if chinese else result.provider.name_en
    model = result.model

    if not result.supported:
        if chinese:
            return (
                f"当前厂商：{provider}\n"
                f"当前模型：{model}\n"
                f"该厂商未提供 gai 已接入的余额查询接口。\n"
                f"当前已支持：{_SUPPORTED_PROVIDER_HINTS_CN}。\n"
                f"请到该厂商控制台查看账单，或更换已支持厂商的 base_url。"
            )
        return (
            f"Provider: {provider}\n"
            f"Model: {model}\n"
            f"This provider has no balance API wired into gai yet.\n"
            f"Currently supported: {_SUPPORTED_PROVIDER_HINTS_EN}.\n"
            f"Check billing in the provider console, or switch base_url to a supported vendor."
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
            if item.remaining is not None:
                lines.append(f"剩余额度：{item.remaining}{unit}")
            if item.total is not None and item.remaining is None:
                lines.append(f"可用总额：{item.total}{unit}")
            elif item.total is not None and item.remaining is not None:
                lines.append(f"已购额度：{item.total}{unit}")
            if item.usage is not None:
                lines.append(f"已使用：{item.usage}{unit}")
            if item.topped_up is not None:
                lines.append(f"充值余额：{item.topped_up}{unit}")
            if item.granted is not None:
                lines.append(f"赠送余额：{item.granted}{unit}")
            if item.charge is not None:
                lines.append(f"充值余额：{item.charge}{unit}")
            if item.gift is not None and item.granted is None:
                lines.append(f"赠送余额：{item.gift}{unit}")
            if item.cash is not None:
                lines.append(f"现金余额：{item.cash}{unit}")
            if item.voucher is not None:
                lines.append(f"代金券：{item.voucher}{unit}")
        if result.note_cn:
            lines.append(result.note_cn)
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
            if item.remaining is not None:
                lines.append(f"Remaining: {item.remaining}{unit}")
            if item.total is not None and item.remaining is None:
                lines.append(f"Total balance: {item.total}{unit}")
            elif item.total is not None and item.remaining is not None:
                lines.append(f"Purchased: {item.total}{unit}")
            if item.usage is not None:
                lines.append(f"Used: {item.usage}{unit}")
            if item.topped_up is not None:
                lines.append(f"Topped-up: {item.topped_up}{unit}")
            if item.granted is not None:
                lines.append(f"Granted: {item.granted}{unit}")
            if item.charge is not None:
                lines.append(f"Charged: {item.charge}{unit}")
            if item.gift is not None and item.granted is None:
                lines.append(f"Gift balance: {item.gift}{unit}")
            if item.cash is not None:
                lines.append(f"Cash: {item.cash}{unit}")
            if item.voucher is not None:
                lines.append(f"Voucher: {item.voucher}{unit}")
        if result.note_en:
            lines.append(result.note_en)
    return "\n".join(lines)


def _first_amount(result: BalanceResult) -> str | None:
    for item in result.items:
        currency = item.currency or ""
        unit = f" {currency}" if currency else ""
        for value in (item.remaining, item.total, item.cash, item.gift):
            if value is not None:
                return f"{value}{unit}"
    return None


def format_balance_brief(result: BalanceResult, *, chinese: bool = False) -> str:
    """One-line balance for config --list."""
    provider = result.provider.name_cn if chinese else result.provider.name_en
    if not result.supported:
        if chinese:
            return f"{provider}不支持余额查询"
        return f"{provider} does not support balance lookup"
    amount = _first_amount(result)
    if amount:
        return f"{amount}（{provider}）" if chinese else f"{amount} ({provider})"
    if chinese:
        return f"已查询（{provider}），无明细金额"
    return f"queried ({provider}), no amount returned"
