"""Configuration editor model: preview first, compare state, then apply once."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import tomllib

from gai.common import config
from gai.setup.config_store import config_lock, write_config
from gai.setup.environment import NAMES, UserEnvironment, safe_value, supported, validate, validate_url

REVIEW_FIELDS = {"max_diff_chars", "ignore_patterns", "fail_on", "require_complete", "rules"}
PERSONAL_FIELDS = REVIEW_FIELDS | {"current", "api_key", "base_url", "model", "timeout"}
DEFAULT_REVIEW = {"max_diff_chars": config.DEFAULT_MAX_DIFF_CHARS,
                  "ignore_patterns": list(config.DEFAULT_IGNORE_PATTERNS), "fail_on": "none",
                  "require_complete": False, "rules": []}


def read_file(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (ValueError, OSError):
        raise ValueError(f"无法读取配置文件，请检查 TOML 格式和访问权限：{path}") from None


def effective(file_cfg, project, env) -> dict:
    settings = config.resolve_settings(file_cfg, project, env)
    values = asdict(settings)
    llm = file_cfg.get("llm", {})
    profiles = config._file_profiles(llm)
    profile = settings.profile
    fields = profiles.get(profile, {})
    keys = {
        "profile": ["GAI_PROFILE"], "timeout": ["GAI_TIMEOUT"],
        "max_diff_chars": ["GAI_MAX_DIFF_CHARS"],
    }
    if profile.isdigit():
        suffix = "" if profile == "0" else profile
        for field in ("api_key", "base_url", "model"):
            keys[field] = ["GAI_" + field.upper() + suffix]
            if profile == "0" and field != "model":
                keys[field].append("OPENAI_" + field.upper())
    result = {}
    for field, value in values.items():
        source = "默认值"
        option = "rules" if field == "review_rules" else field
        if field in {"api_key", "base_url", "model"} and fields.get(field):
            source = f"个人配置 · {profile}"
        elif field == "profile" and llm.get("current"):
            source = "个人配置 · llm.current"
        elif field == "timeout" and llm.get("timeout"):
            source = "个人配置"
        elif option in file_cfg.get("review", {}):
            source = "个人配置"
        if option in project.get("review", {}):
            source = "项目配置 · .gai.toml"
        for name in keys.get(field, []):
            if env.get(name) and (name != "GAI_PROFILE" or env[name].strip()):
                source = "环境变量 · " + name
                break
        result[field] = {"value": safe_value(field, value), "source": source}
    return result


def safe_effective(file_cfg, project, env):
    try:
        return effective(file_cfg, project, env)
    except (RuntimeError, ValueError, TypeError):
        return {"error": {"value": "当前配置含无效值，请修正后预览", "source": "配置校验"}}


class ConfigEditor:
    def __init__(self, *, project_root: Path | None = None, environ=None, registry=None):
        self.path = config.CONFIG_FILE
        self.project_path = project_root / ".gai.toml" if project_root else None
        self.env = os.environ if environ is None else environ
        self.registry = registry if registry is not None else UserEnvironment()
        self.pending = None

    def snapshot(self):
        personal = read_file(self.path)
        project = read_file(self.project_path)
        env = {k: v for k, v in self.env.items() if supported(k)}
        user = self.registry.read()
        machine = self.registry.read(machine=True)
        raw = [personal, project, env, user, machine]
        # Include exact bytes: even external comment/format edits invalidate a preview.
        raw += [p.read_bytes().hex() if p and p.exists() else None for p in (self.path, self.project_path)]
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        return personal, project, env, user, machine, digest

    def state(self):
        personal, project, env, user, machine, _ = self.snapshot()
        llm = personal.get("llm", {})
        profiles = config._file_profiles(llm)
        profiles.setdefault("0", {})
        for name in env.keys() | user.keys() | machine.keys():
            from gai.setup.environment import NUMBERED
            match = NUMBERED.fullmatch(name)
            if match:
                profiles.setdefault(match.group(2), {})
        current = str(llm.get("current") or "0")
        profiles.setdefault(current, {})
        for body in profiles.values():
            body["has_api_key"] = bool(body.pop("api_key", ""))
        rows = []
        for name in sorted(set(NAMES) | env.keys() | user.keys() | machine.keys()):
            rows.append({"name": name, "process": safe_value(name, env.get(name)),
                         "user": safe_value(name, user.get(name, (None,))[0]),
                         "machine": safe_value(name, machine.get(name, (None,))[0]),
                         "in_process": name in env, "in_user": name in user})
        return {"personal_path": str(self.path), "project_path": str(self.project_path or ""),
                "profiles": profiles, "current": current,
                "timeout": llm.get("timeout", config.DEFAULT_TIMEOUT),
                "review": {**DEFAULT_REVIEW, **personal.get("review", {})},
                "project": project.get("review", {}), "environment": rows,
                "user_environment_supported": self.registry.available,
                "effective": safe_effective(personal, project, env)}

    def _edit_file(self, personal, project, payload):
        target = payload["target"]
        fields = payload.get("fields")
        allowed = PERSONAL_FIELDS if target == "personal" else REVIEW_FIELDS
        if not isinstance(fields, dict) or not fields or set(fields) - allowed:
            raise ValueError("请选择有效的配置字段")
        changes = []
        candidate = deepcopy(personal if target == "personal" else project)
        if target == "project" and self.project_path is None:
            raise ValueError("当前目录不是 Git 仓库，不能保存项目配置")
        profile = payload.get("profile", "0")
        if not isinstance(profile, str) or not profile.strip() or profile != profile.strip() or len(profile) > 100:
            raise ValueError("配置档名称须为 1–100 个字符，且两端不能有空格")
        for field, value in fields.items():
            if value is None and target != "project":
                raise ValueError("个人配置请填写具体值")
            if value is not None:
                if field in {"api_key", "base_url", "model", "current"}:
                    if not isinstance(value, str) or any(c in value for c in "\x00\r\n"):
                        raise ValueError(f"{field}: 必须为单行文本")
                    if field != "api_key" and not value.strip():
                        raise ValueError(f"{field}: 不能为空")
                    if field == "current" and value != value.strip():
                        raise ValueError("current: 配置档名称两端不能有空格")
                    if field == "base_url":
                        validate_url(value)
                if field in {"ignore_patterns", "rules"} and (not isinstance(value, list) or
                        any(not isinstance(v, str) for v in value)):
                    raise ValueError(f"{field}: 请每行填写一项")
                if field == "max_diff_chars" and (type(value) is not int or value <= 0):
                    raise ValueError("max_diff_chars: 必须为正整数")
                if field == "timeout" and (type(value) not in (float, int) or value <= 0):
                    raise ValueError("timeout: 必须为正数")
            if field in REVIEW_FIELDS:
                table = candidate.setdefault("review", {})
            else:
                table = candidate.setdefault("llm", {})
                if field in {"api_key", "base_url", "model"}:
                    # Migrate legacy profile 0 before editing; retain other profiles.
                    normalized = config._file_profiles(table)
                    for name, body in table.get("profiles", {}).items():
                        if isinstance(body, dict):
                            normalized[name] = {**body, **normalized.get(name, {})}
                    table["profiles"] = normalized
                    for key in ("api_key", "base_url", "model"):
                        table.pop(key, None)
                    table = table["profiles"].setdefault(profile, {})
            old = table.get(field)
            if value is None:
                table.pop(field, None)
            else:
                table[field] = value
            if old != value:
                changes.append({"field": field, "before": safe_value(field, old),
                                "after": safe_value(field, value), "removed": value is None})
        # Validate the saved layer itself even if environment/project overrides hide it.
        config.resolve_settings(candidate if target == "personal" else {},
                                candidate if target == "project" else {}, {})
        return candidate, changes

    def _fallback(self, name, personal, project, env):
        """Resolve the edited setting, even for an inactive numbered profile."""
        from gai.setup.environment import NUMBERED
        match = NUMBERED.fullmatch(name)
        field = None
        lookup = dict(env)
        if match or name in {"GAI_API_KEY", "OPENAI_API_KEY", "GAI_BASE_URL", "OPENAI_BASE_URL", "GAI_MODEL"}:
            lookup["GAI_PROFILE"] = match.group(2) if match else "0"
            field = match.group(1).lower() if match else name.split("_", 1)[1].lower()
        field = field or {"GAI_PROFILE": "profile", "GAI_TIMEOUT": "timeout",
                          "GAI_MAX_DIFF_CHARS": "max_diff_chars"}.get(name)
        if field:
            return effective(personal, project, lookup)[field]
        defaults = {"GAI_GIT_TIMEOUT": "60 秒", "GAI_GIT_NETWORK_TIMEOUT": "180 秒",
                    "GAI_HISTORY": "启用", "GAI_USAGE_LOG": "<仓库>/.gai/usage.jsonl",
                    "GAI_HISTORY_LOG": "<仓库>/.gai/commands.jsonl",
                    "GAI_USAGE_LOG_GLOBAL": "~/.gai/usage.jsonl",
                    "GAI_HISTORY_LOG_GLOBAL": "~/.gai/commands.jsonl"}
        return {"value": env.get(name) or defaults.get(name),
                "source": "环境变量 · " + name if env.get(name) else "默认值"}

    def preview(self, payload: dict):
        if not isinstance(payload, dict) or payload.get("target") not in {"personal", "project", "environment"}:
            raise ValueError("请选择保存位置")
        personal, project, env, user, machine, digest = self.snapshot()
        before = safe_effective(personal, project, env)
        target = payload["target"]
        candidate = None
        fallback = None
        fallbacks = []
        if target == "environment":
            edits = payload.get("changes")
            if edits is None:
                if "value" not in payload:
                    raise ValueError("缺少环境变量值或删除操作")
                edits = {payload.get("name"): payload["value"]}
            if not isinstance(edits, dict) or not edits or len(edits) > 128:
                raise ValueError("请提供 1–128 项环境变量修改")
            for name, value in edits.items():
                validate(name, value)
            scope = payload.get("scope")
            if scope not in {"process", "user"}:
                raise ValueError("请选择环境变量作用范围")
            if scope == "user" and not self.registry.available:
                raise ValueError("当前系统不支持 Windows 用户环境变量编辑")
            changes = []
            for name, value in edits.items():
                if scope == "user" and value is None and name not in user:
                    raise ValueError("没有此用户级变量可删除；当前进程中的同名值可能来自终端或系统级设置")
                old = user.get(name, (None,))[0] if scope == "user" else env.get(name)
                if value is None:
                    env.pop(name, None)
                    if scope == "user" and name in machine:
                        env[name] = self.registry.expanded(machine[name])
                else:
                    env[name] = value
                changes.append({"field": name, "before": safe_value(name, old),
                                "after": safe_value(name, value), "removed": value is None})
            # Resolve the whole draft, permitting repair of multiple invalid values.
            for name, value in edits.items():
                resolved = self._fallback(name, personal, project, env)
                if value is None and scope == "user" and name in machine:
                    resolved = {**resolved, "note": "系统级同名变量仍存在，删除用户变量不会删除系统变量"}
                fallbacks.append({"name": name, **resolved})
            fallback = {k: v for k, v in fallbacks[0].items() if k != "name"} if len(fallbacks) == 1 else None
            payload = {"target": target, "scope": scope, "changes": deepcopy(edits)}
        else:
            candidate, changes = self._edit_file(personal, project, payload)
            if target == "personal":
                personal = candidate
            else:
                project = candidate
        after = effective(personal, project, env)
        token = secrets.token_urlsafe(24)
        self.pending = {"ticket": token, "expires": time.monotonic() + 600,
                        "digest": digest, "payload": deepcopy(payload), "candidate": candidate,
                        "env": env, "personal": personal, "project": project}
        notes = ["保存前请检查当前生效值及其来源；环境变量可能覆盖文件设置。"]
        if target == "environment":
            if payload["scope"] == "user":
                notes.append("将写入当前 Windows 用户的环境变量，并同步到本 GUI 进程。请重新打开终端或 IDE；已有终端不会更新。删除后的预览保留系统级变量，终端启动脚本仍可能再次覆盖。")
            else:
                notes.append("仅本 GUI 服务进程及连接测试生效；关闭后失效，不会修改启动它的终端，也不会影响其他 gai 命令。")
        else:
            notes.append("保存会规范化 TOML 排版并去掉注释；其他已有字段保留。")
        return {"ticket": token, "changes": changes, "before": before, "after": after,
                "fallback": fallback, "fallbacks": fallbacks, "notes": notes,
                "destination": str(self.path if target == "personal" else self.project_path) if target != "environment"
                else ("Windows 当前用户环境变量" if payload["scope"] == "user" else "仅本 GUI 进程")}

    def _ticket(self, ticket):
        pending = self.pending
        if (not isinstance(ticket, str) or pending is None or not secrets.compare_digest(ticket, pending["ticket"])
                or time.monotonic() > pending["expires"]):
            raise ValueError("预览已失效，请重新预览")
        if self.snapshot()[-1] != pending["digest"]:
            self.pending = None
            raise ValueError("配置已被其他操作修改，请刷新后重新预览")
        return pending

    def apply(self, ticket):
        pending = self._ticket(ticket)
        target = pending["payload"]["target"]
        path = self.path if target == "personal" else self.project_path
        with config_lock(path) if target != "environment" else nullcontext():
            pending = self._ticket(ticket)
            self.pending = None
            if target == "environment":
                payload = pending["payload"]
                if payload["scope"] == "user":
                    self.registry.write(payload["changes"])
                for name in payload["changes"]:
                    if name in pending["env"]:
                        self.env[name] = pending["env"][name]
                    else:
                        self.env.pop(name, None)
            else:
                write_config(path, pending["candidate"])
        return self.state()

    def test_connection(self, ticket):
        pending = self._ticket(ticket)
        settings = config.resolve_settings(pending["personal"], pending["project"], pending["env"])
        validate_url(settings.base_url)
        if not settings.api_key:
            raise ValueError("当前生效配置未设置 API Key")
        import httpx
        try:
            # No chat/completions request; redirects never forward credentials.
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                with client.stream("GET", settings.base_url.rstrip("/") + "/models",
                                   headers={"Authorization": "Bearer " + settings.api_key}) as response:
                    if response.status_code in (404, 405):
                        return {"message": "服务不提供模型列表，无法通过此接口验证连接；未发送审查请求。"}
                    if response.status_code != 200:
                        return {"message": f"连接检查返回 HTTP {response.status_code}，请检查地址、密钥及服务状态。"}
                    return {"message": "模型列表接口连接成功；这不保证当前模型有调用权限或剩余额度。"}
        except (httpx.HTTPError, ValueError):
            return {"message": "连接失败或超时，请检查地址、网络及密钥。"}
