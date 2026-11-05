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
import json
import math
import re
import stat
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
    fail_on: str = "none"
    require_complete: bool = False
    review_rules: tuple[str, ...] = ()


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
    return json.dumps(value, ensure_ascii=False)


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


def _env_profile_fields(name: str, env=None) -> dict[str, str]:
    """Env overlays for a numeric profile id (\"0\", \"1\", ...). Named → empty."""
    if not name.isdigit():
        return {}
    env = os.environ if env is None else env
    if name == DEFAULT_PROFILE:
        key = env.get("GAI_API_KEY") or env.get("OPENAI_API_KEY") or ""
        url = (
            env.get("GAI_BASE_URL")
            or env.get("OPENAI_BASE_URL")
            or ""
        )
        model = env.get("GAI_MODEL") or ""
    else:
        key = env.get(f"GAI_API_KEY{name}") or ""
        url = env.get(f"GAI_BASE_URL{name}") or ""
        model = env.get(f"GAI_MODEL{name}") or ""
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


def get_active_profile_name(file_cfg: dict | None = None, env=None) -> str:
    env = os.environ if env is None else env
    env_prof = (env.get("GAI_PROFILE") or "").strip()
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


def load_project_config() -> dict:
    # Only non-secret review settings are accepted from the repository.
    from gai.common.git.core import run_git, GitError
    try:
        located = run_git("rev-parse", "--show-toplevel", trace=False)
    except GitError:
        located = None
    if located is not None and located.returncode == 0:
        policy_path = Path(located.stdout.strip()) / ".gai.toml"
        try:
            with policy_path.open("rb") as stream:
                project = tomllib.load(stream)
        except FileNotFoundError:
            project = {}
        except (OSError, ValueError) as exc:
            raise RuntimeError("无法读取项目规则 / Cannot read .gai.toml") from exc
        return project
    return {}


def load_settings() -> Settings:
    from gai.review.policy import overrides
    return resolve_settings(_load_toml(), load_project_config(), os.environ, overrides())


def resolve_settings(file_cfg: dict, project: dict, env, cli: dict | None = None) -> Settings:
    """Resolve explicit inputs, also used for GUI previews without changing the process."""
    from gai.review.policy import LEVELS
    llm = file_cfg.get("llm", {}) if isinstance(file_cfg.get("llm"), dict) else {}
    review = file_cfg.get("review", {}) if isinstance(file_cfg.get("review"), dict) else {}
    if set(project) - {"review"} or not isinstance(project.get("review", {}), dict):
        raise RuntimeError(".gai.toml only accepts a [review] table; keep credentials in personal config")
    project_review = project.get("review", {})
    allowed = {"ignore_patterns", "max_diff_chars", "fail_on", "require_complete", "rules"}
    if set(project_review) - allowed:
        raise RuntimeError("Unknown .gai.toml review settings: " + ", ".join(sorted(set(project_review) - allowed)))
    review = {**review, **project_review, **(cli or {})}
    fail_on = review.get("fail_on", "none")
    complete = review.get("require_complete", False)
    rules = review.get("rules", [])
    if (not isinstance(fail_on, str) or fail_on not in LEVELS or type(complete) is not bool or not isinstance(rules, list)
            or any(not isinstance(rule, str) for rule in rules)):
        raise RuntimeError("Invalid review policy: fail_on, require_complete or rules")

    ignore = review.get("ignore_patterns")
    if ignore is not None and (not isinstance(ignore, list) or any(not isinstance(p, str) for p in ignore)):
        raise RuntimeError("ignore_patterns must be an array of strings")
    if isinstance(ignore, list):
        ignore_patterns = tuple(str(x) for x in ignore)
    else:
        ignore_patterns = DEFAULT_IGNORE_PATTERNS
    limit_value = env.get("GAI_MAX_DIFF_CHARS") or review.get("max_diff_chars", DEFAULT_MAX_DIFF_CHARS)
    if isinstance(limit_value, bool) or not isinstance(limit_value, (str, int)):
        raise RuntimeError("max_diff_chars must be a positive integer")
    try:
        diff_limit = int(limit_value)
    except ValueError as exc:
        raise RuntimeError("max_diff_chars must be a positive integer") from exc
    if diff_limit <= 0:
        raise RuntimeError("max_diff_chars must be positive")

    profile = get_active_profile_name(file_cfg, env)
    file_map = _file_profiles(llm)
    file_body = file_map.get(profile, {})
    env_body = _env_profile_fields(profile, env)

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
            env.get("GAI_TIMEOUT")
            or llm.get("timeout")
            or DEFAULT_TIMEOUT
        ),
        max_diff_chars=diff_limit,
        ignore_patterns=ignore_patterns,
        profile=profile,
        fail_on=fail_on,
        require_complete=complete,
        review_rules=tuple(rules),
    )
    if settings.max_diff_chars <= 0:
        raise RuntimeError("max_diff_chars must be positive")
    if not math.isfinite(settings.timeout) or settings.timeout <= 0:
        raise RuntimeError("timeout must be a positive finite number")
    return settings


def save_settings(**kwargs) -> Path:
    from gai.common.jsonl import log_lock
    with log_lock(CONFIG_FILE):
        return _save_settings(**kwargs)


def _save_settings(
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
    for name, body in llm.get("profiles", {}).items():
        if isinstance(body, dict):
            profiles[name] = {**body, **profiles.get(name, {})}
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

    if timeout is not None:
        llm["timeout"] = timeout
    else:
        llm.setdefault("timeout", DEFAULT_TIMEOUT)

    if max_diff_chars is not None:
        review["max_diff_chars"] = max_diff_chars
    else:
        review.setdefault("max_diff_chars", DEFAULT_MAX_DIFF_CHARS)

    review.setdefault("ignore_patterns", list(DEFAULT_IGNORE_PATTERNS))

    # Drop legacy flat credential keys; profiles own them now.
    for legacy in ("api_key", "base_url", "model"):
        llm.pop(legacy, None)
    llm["profiles"] = profiles

    existing["llm"] = llm
    existing["review"] = review
    from gai.setup.config_store import write_config
    write_config(CONFIG_FILE, existing)
    return CONFIG_FILE


def _tighten_config_permissions(path: Path) -> None:
    """Best-effort: restrict config.toml to the current user (contains API keys)."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        # Windows / some network FS may ignore or reject POSIX mode bits.
        pass


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
    _ = chinese
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
    return rows


def settings_from_profile(profile: ProfileInfo, template: Settings | None = None) -> Settings:
    """Build Settings for a listed profile (timeout/review from template or defaults)."""
    base = template or Settings()
    return Settings(
        api_key=profile.api_key,
        base_url=profile.base_url or DEFAULT_BASE_URL,
        model=profile.model or DEFAULT_MODEL,
        timeout=base.timeout,
        max_diff_chars=base.max_diff_chars,
        ignore_patterns=base.ignore_patterns,
        profile=profile.name,
    )


def format_profile_label(name: str, *, chinese: bool = False) -> str:
    if name.isdigit():
        return f"编号 {name}" if chinese else f"#{name}"
    return f"配置档 {name}" if chinese else f"profile {name}"


def format_profiles_overview(*, chinese: bool = False) -> str:
    profiles = list_profiles()
    keyed = [p for p in profiles if p.api_key]
    active = next((p for p in profiles if p.active), None)
    lines: list[str] = []
    if chinese:
        lines.append(f"已配置 API Key：{len(keyed)} 个")
        if active:
            lines.append(f"当前使用：{format_profile_label(active.name, chinese=True)}")
        else:
            lines.append("当前使用：（无）")
    else:
        lines.append(f"Configured API keys: {len(keyed)}")
        if active:
            lines.append(f"In use: {format_profile_label(active.name, chinese=False)}")
        else:
            lines.append("In use: (none)")
    return "\n".join(lines)
