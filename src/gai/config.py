"""Configuration: env vars > ~/.gai/config.toml > defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".gai"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_DIFF_CHARS = 80_000

# Filenames / suffixes skipped when building the staged diff payload.
DEFAULT_IGNORE_PATTERNS = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "uv.lock",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.gz",
    "*.woff",
    "*.woff2",
    "*.ttf",
)


@dataclass
class Settings:
    api_key: str = "" #接收大模型的密钥
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS


def _load_toml() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def load_settings() -> Settings:
    file_cfg = _load_toml()
    llm = file_cfg.get("llm", {}) if isinstance(file_cfg.get("llm"), dict) else {}
    review = file_cfg.get("review", {}) if isinstance(file_cfg.get("review"), dict) else {}

    ignore = review.get("ignore_patterns")
    if isinstance(ignore, list) and ignore:
        ignore_patterns = tuple(str(x) for x in ignore)
    else:
        ignore_patterns = DEFAULT_IGNORE_PATTERNS

    settings = Settings(
        api_key=str(
            os.environ.get("GAI_API_KEY") # 获取操作系统中配置的api key
            or os.environ.get("OPENAI_API_KEY")
            or llm.get("api_key")
            or ""
        ),
        base_url=str(
            os.environ.get("GAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or llm.get("base_url")
            or DEFAULT_BASE_URL
        ).rstrip("/"),
        model=str(
            os.environ.get("GAI_MODEL")
            or llm.get("model")
            or DEFAULT_MODEL
        ),
        timeout=float(
            os.environ.get("GAI_TIMEOUT")
            or llm.get("timeout")
            or DEFAULT_TIMEOUT
        ),
        max_diff_chars=int(
            os.environ.get("GAI_MAX_DIFF_CHARS")
            or review.get("max_diff_chars")
            or DEFAULT_MAX_DIFF_CHARS
        ),
        ignore_patterns=ignore_patterns,
    )
    return settings


def save_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
    max_diff_chars: int | None = None,
) -> Path:
    """Merge provided fields into ~/.gai/config.toml and write it back."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_toml()
    llm = dict(existing.get("llm") or {})
    review = dict(existing.get("review") or {})

    current = load_settings()
    if api_key is not None:
        llm["api_key"] = api_key
    elif current.api_key and "api_key" not in llm:
        llm["api_key"] = current.api_key

    if base_url is not None:
        llm["base_url"] = base_url.rstrip("/")
    else:
        llm.setdefault("base_url", current.base_url)

    if model is not None:
        llm["model"] = model
    else:
        llm.setdefault("model", current.model)

    if timeout is not None:
        llm["timeout"] = timeout
    else:
        llm.setdefault("timeout", current.timeout)

    if max_diff_chars is not None:
        review["max_diff_chars"] = max_diff_chars
    else:
        review.setdefault("max_diff_chars", current.max_diff_chars)

    review.setdefault("ignore_patterns", list(current.ignore_patterns))

    # Write a simple TOML by hand to avoid an extra dependency.
    lines = ["# gai configuration", "", "[llm]"]
    for key in ("api_key", "base_url", "model", "timeout"):
        if key not in llm:
            continue
        val = llm[key]
        if isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        else:
            lines.append(f"{key} = {val}")

    lines.extend(["", "[review]", f"max_diff_chars = {review['max_diff_chars']}"])
    patterns = review.get("ignore_patterns") or list(DEFAULT_IGNORE_PATTERNS)
    lines.append("ignore_patterns = [")
    for p in patterns:
        escaped = str(p).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  "{escaped}",')
    lines.append("]")
    lines.append("")

    CONFIG_FILE.write_text("\n".join(lines), encoding="utf-8")
    return CONFIG_FILE


def mask_secret(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def settings_summary(settings: Settings) -> dict[str, str]:
    return {
        "api_key": mask_secret(settings.api_key),
        "base_url": settings.base_url,
        "model": settings.model,
        "timeout": str(settings.timeout),
        "max_diff_chars": str(settings.max_diff_chars),
        "config_file": str(CONFIG_FILE) if CONFIG_FILE.is_file() else "(none)",
    }
