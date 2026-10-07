"""Configuration: env vars > ~/.gai/config.toml > defaults.

LLM credentials support multiple profiles:

- Profile ``0``: ``GAI_API_KEY`` / ``OPENAI_API_KEY``, ``GAI_BASE_URL`` /
  ``OPENAI_BASE_URL``, ``GAI_MODEL`` (unnumbered env = index 0).
- Profile ``N`` (N >= 1): ``GAI_API_KEYN``, ``GAI_BASE_URLN``, ``GAI_MODELN``.
- Named profiles in ``~/.gai/config.toml`` under ``[llm.profiles."<id>"]``.
- Active profile: ``GAI_PROFILE`` env > ``llm.current`` in file > ``"0"``.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".gai"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_DIFF_CHARS = 80_000
DEFAULT_PROFILE = "0"

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

_ENV_INDEX_RE = re.compile(r"^GAI_(?:API_KEY|BASE_URL|MODEL)(\d+)$")


@dataclass
class Settings:
    api_key: str = ""  # 接收大模型的密钥
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    profile: str = DEFAULT_PROFILE


@dataclass
class ProfileInfo:
    """One discoverable LLM profile (env and/or file)."""

    name: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)
    active: bool = False


def _load_toml() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _file_profiles(llm: dict) -> dict[str, dict[str, Any]]:
    """Return profile id -> {api_key, base_url, model} from toml llm section."""
    raw = llm.get("profiles")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for name, body in raw.items():
            if not isinstance(body, dict):
                continue
            out[str(name)] = {
                "api_key": str(body.get("api_key") or ""),
                "base_url": str(body.get("base_url") or "").rstrip("/"),
                "model": str(body.get("model") or ""),
            }
    # Legacy flat [llm] api_key/base_url/model → profile "0" if missing.
    legacy_key = str(llm.get("api_key") or "")
    legacy_url = str(llm.get("base_url") or "").rstrip("/")
    legacy_model = str(llm.get("model") or "")
    if legacy_key or legacy_url or legacy_model:
        base = out.get(DEFAULT_PROFILE, {"api_key": "", "base_url": "", "model": ""})
        if legacy_key and not base.get("api_key"):
            base["api_key"] = legacy_key
        if legacy_url and not base.get("base_url"):
            base["base_url"] = legacy_url
        if legacy_model and not base.get("model"):
            base["model"] = legacy_model
        out[DEFAULT_PROFILE] = base
    return out


def _env_profile_fields(name: str) -> dict[str, str]:
    """Env overlays for a numeric profile id (\"0\", \"1\", ...). Named → empty."""
    if not name.isdigit():
        return {}
    if name == DEFAULT_PROFILE:
        key = os.environ.get("GAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        url = (
            os.environ.get("GAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or ""
        )
        model = os.environ.get("GAI_MODEL") or ""
    else:
        key = os.environ.get(f"GAI_API_KEY{name}") or ""
        url = os.environ.get(f"GAI_BASE_URL{name}") or ""
        model = os.environ.get(f"GAI_MODEL{name}") or ""
    fields: dict[str, str] = {}
    if key:
        fields["api_key"] = key
    if url:
        fields["base_url"] = url.rstrip("/")
    if model:
        fields["model"] = model
    return fields


def _discover_env_profile_names() -> list[str]:
    names: set[str] = set()
    if any(
        os.environ.get(k)
        for k in (
            "GAI_API_KEY",
            "OPENAI_API_KEY",
            "GAI_BASE_URL",
            "OPENAI_BASE_URL",
            "GAI_MODEL",
        )
    ):
        names.add(DEFAULT_PROFILE)
    for key in os.environ:
        m = _ENV_INDEX_RE.match(key)
        if m and os.environ.get(key):
            names.add(m.group(1))
    return sorted(names, key=lambda n: (not n.isdigit(), int(n) if n.isdigit() else 0, n))


def get_active_profile_name(file_cfg: dict | None = None) -> str:
    env_prof = (os.environ.get("GAI_PROFILE") or "").strip()
    if env_prof:
        return env_prof
    cfg = file_cfg if file_cfg is not None else _load_toml()
    llm = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}
    current = str(llm.get("current") or "").strip()
    return current or DEFAULT_PROFILE


def list_profiles() -> list[ProfileInfo]:
    """All profiles from env indices and config file; mark the active one."""
    file_cfg = _load_toml()
    llm = file_cfg.get("llm", {}) if isinstance(file_cfg.get("llm"), dict) else {}
    file_map = _file_profiles(llm)
    active = get_active_profile_name(file_cfg)

    names = set(file_map) | set(_discover_env_profile_names())
    if active:
        names.add(active)

    def _sort_key(n: str) -> tuple:
        if n.isdigit():
            return (0, int(n), n)
        return (1, 0, n)

    result: list[ProfileInfo] = []
    for name in sorted(names, key=_sort_key):
        file_body = file_map.get(name, {})
        env_body = _env_profile_fields(name)
        api_key = env_body.get("api_key") or str(file_body.get("api_key") or "")
        base_url = env_body.get("base_url") or str(file_body.get("base_url") or "")
        model = env_body.get("model") or str(file_body.get("model") or "")
        sources: list[str] = []
        if env_body:
            sources.append("env")
        if file_body and any(file_body.get(k) for k in ("api_key", "base_url", "model")):
            sources.append("file")
        if not sources:
            sources.append("empty")
        result.append(
            ProfileInfo(
                name=name,
                api_key=api_key,
                base_url=base_url or DEFAULT_BASE_URL,
                model=model or DEFAULT_MODEL,
                sources=tuple(sources),
                active=name == active,
            )
        )
    return result


def load_settings() -> Settings:
    file_cfg = _load_toml()
    llm = file_cfg.get("llm", {}) if isinstance(file_cfg.get("llm"), dict) else {}
    review = file_cfg.get("review", {}) if isinstance(file_cfg.get("review"), dict) else {}

    ignore = review.get("ignore_patterns")
    if isinstance(ignore, list) and ignore:
        ignore_patterns = tuple(str(x) for x in ignore)
    else:
        ignore_patterns = DEFAULT_IGNORE_PATTERNS

    profile = get_active_profile_name(file_cfg)
    file_map = _file_profiles(llm)
    file_body = file_map.get(profile, {})
    env_body = _env_profile_fields(profile)

    api_key = str(
        env_body.get("api_key")
        or file_body.get("api_key")
        or ""
    )
    base_url = str(
        env_body.get("base_url")
        or file_body.get("base_url")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    model = str(
        env_body.get("model")
        or file_body.get("model")
        or DEFAULT_MODEL
    )

    settings = Settings(
        api_key=api_key,
        base_url=base_url,
        model=model,
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
        profile=profile,
    )
    return settings


def save_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
    max_diff_chars: int | None = None,
    profile: str | None = None,
    set_current: str | None = None,
) -> Path:
    """Merge provided fields into ~/.gai/config.toml and write it back.

    Credential fields go into ``[llm.profiles."<id>"]``. ``profile`` selects
    the target profile (default: current). ``set_current`` updates
    ``llm.current``.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_toml()
    llm = dict(existing.get("llm") or {}) if isinstance(existing.get("llm"), dict) else {}
    review = dict(existing.get("review") or {}) if isinstance(existing.get("review"), dict) else {}

    profiles = _file_profiles(llm)
    current_name = str(llm.get("current") or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
    target = (profile or set_current or current_name or DEFAULT_PROFILE).strip()
    if not target:
        target = DEFAULT_PROFILE

    credential_update = any(v is not None for v in (api_key, base_url, model))
    if credential_update or target in profiles:
        body = dict(
            profiles.get(target) or {"api_key": "", "base_url": "", "model": ""}
        )
        if api_key is not None:
            body["api_key"] = api_key
        if base_url is not None:
            body["base_url"] = base_url.rstrip("/")
        if model is not None:
            body["model"] = model
        if not body.get("base_url"):
            body["base_url"] = DEFAULT_BASE_URL
        if not body.get("model"):
            body["model"] = DEFAULT_MODEL
        profiles[target] = body

    if set_current is not None:
        llm["current"] = set_current.strip() or DEFAULT_PROFILE
    elif "current" not in llm:
        llm["current"] = target

    current_effective = load_settings()
    if timeout is not None:
        llm["timeout"] = timeout
    else:
        llm.setdefault("timeout", current_effective.timeout)

    if max_diff_chars is not None:
        review["max_diff_chars"] = max_diff_chars
    else:
        review.setdefault("max_diff_chars", current_effective.max_diff_chars)

    review.setdefault("ignore_patterns", list(current_effective.ignore_patterns))

    # Drop legacy flat credential keys; profiles own them now.
    for legacy in ("api_key", "base_url", "model"):
        llm.pop(legacy, None)
    llm["profiles"] = profiles

    lines = ["# gai configuration", "", "[llm]"]
    lines.append(f"current = {_toml_str(str(llm.get('current') or DEFAULT_PROFILE))}")
    timeout_val = llm.get("timeout", DEFAULT_TIMEOUT)
    lines.append(f"timeout = {timeout_val}")

    for name in sorted(
        profiles.keys(),
        key=lambda n: (0, int(n), n) if n.isdigit() else (1, 0, n),
    ):
        p = profiles[name]
        lines.append("")
        lines.append(f"[llm.profiles.{_toml_str(name)}]")
        for key in ("api_key", "base_url", "model"):
            val = str(p.get(key) or "")
            if key == "api_key" and not val:
                continue
            if key == "base_url" and not val:
                continue
            if key == "model" and not val:
                continue
            lines.append(f"{key} = {_toml_str(val)}")

    lines.extend(["", "[review]", f"max_diff_chars = {review['max_diff_chars']}"])
    patterns = review.get("ignore_patterns") or list(DEFAULT_IGNORE_PATTERNS)
    lines.append("ignore_patterns = [")
    for p in patterns:
        lines.append(f"  {_toml_str(str(p))},")
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
        "profile": settings.profile,
        "api_key": mask_secret(settings.api_key),
        "base_url": settings.base_url,
        "model": settings.model,
        "timeout": str(settings.timeout),
        "max_diff_chars": str(settings.max_diff_chars),
        "config_file": str(CONFIG_FILE) if CONFIG_FILE.is_file() else "(none)",
    }


def profiles_summary(chinese: bool = False) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for p in list_profiles():
        mark = "*" if p.active else ""
        rows.append(
            {
                "current": mark,
                "profile": p.name,
                "api_key": mask_secret(p.api_key),
                "base_url": p.base_url or DEFAULT_BASE_URL,
                "model": p.model or DEFAULT_MODEL,
                "source": "+".join(p.sources),
            }
        )
    if chinese and not rows:
        return rows
    return rows
