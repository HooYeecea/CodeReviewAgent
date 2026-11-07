"""Allowlisted gai environment settings; never edit shell startup scripts."""
from __future__ import annotations

import math
import os
import re
from urllib.parse import urlsplit

NAMES = (
    "GAI_PROFILE", "GAI_API_KEY", "OPENAI_API_KEY", "GAI_BASE_URL", "OPENAI_BASE_URL",
    "GAI_MODEL", "GAI_TIMEOUT", "GAI_MAX_DIFF_CHARS", "GAI_GIT_TIMEOUT",
    "GAI_GIT_NETWORK_TIMEOUT", "GAI_HISTORY", "GAI_USAGE_LOG", "GAI_USAGE_LOG_GLOBAL",
    "GAI_HISTORY_LOG", "GAI_HISTORY_LOG_GLOBAL",
)
NUMBERED = re.compile(r"GAI_(API_KEY|BASE_URL|MODEL)([1-9][0-9]*)\Z", re.ASCII)


def supported(name: str) -> bool:
    return name in NAMES or bool(NUMBERED.fullmatch(name))


def secret(name: str) -> bool:
    return "api_key" in name.lower()


def safe_value(name: str, value):
    if secret(name):
        return "••••（已设置）" if value else "（未设置）"
    from gai.common.redact import redact_urls
    return redact_urls(value) if isinstance(value, str) else value


def validate_url(value: str) -> None:
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        raise ValueError("API 地址的端口无效") from None
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() for c in value)):
        raise ValueError("API 地址须为完整的 HTTP(S) 地址，不能包含账号、查询参数或片段")


def validate(name: str, value: str | None) -> None:
    if not isinstance(name, str) or not supported(name):
        raise ValueError("仅允许管理 gai 支持的环境变量")
    if value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 16000 or any(c in value for c in "\x00\r\n"):
        raise ValueError(f"{name}: 请填写有效值；删除请使用删除操作")
    if name.endswith("TIMEOUT"):
        try:
            number = float(value)
        except ValueError:
            raise ValueError(f"{name}: 必须为正数秒数") from None
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{name}: 必须为正数秒数")
    if name == "GAI_MAX_DIFF_CHARS" and (not value.isascii() or not value.isdigit() or int(value) <= 0):
        raise ValueError("GAI_MAX_DIFF_CHARS: 必须为正整数")
    if "BASE_URL" in name:
        validate_url(value)
    if name == "GAI_PROFILE" and value != value.strip():
        raise ValueError("配置档名称两端不能有空格")


class UserEnvironment:
    """Current-user registry only. Machine settings are read-only fallbacks."""
    available = os.name == "nt"

    def read(self, *, machine=False) -> dict:
        if not self.available:
            return {}
        import winreg
        root = winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER
        path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment" if machine else "Environment"
        result = {}
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, value, kind = winreg.EnumValue(key, i)
                    name = name.upper()
                    if supported(name) and kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                        result[name] = (value, kind)
        except FileNotFoundError:
            pass
        return result

    def expanded(self, record) -> str:
        if record is None:
            return ""
        value, kind = record
        if self.available:
            import winreg
            if kind == winreg.REG_EXPAND_SZ:
                return winreg.ExpandEnvironmentStrings(value)
        return value

    def write(self, changes: dict[str, str | None]) -> None:
        if not self.available:
            raise ValueError("持久环境变量编辑仅支持 Windows；其他系统请使用个人配置文件")
        for name, value in changes.items():
            validate(name, value)
        import winreg
        before = self.read()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            done = []
            try:
                for name, value in changes.items():
                    if value is None:
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    done.append(name)
            except OSError:
                for name in reversed(done):
                    if name in before:
                        value, kind = before[name]
                        winreg.SetValueEx(key, name, 0, kind, value)
                    else:
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                raise
        try:
            self.broadcast()
        except (OSError, AttributeError):
            # The registry is already saved. Notification is best-effort;
            # the UI always instructs users to restart terminals/IDEs.
            pass

    def broadcast(self):
        # Notify Explorer; already running terminals/IDEs retain their own env.
        import ctypes
        from ctypes import wintypes
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send.restype = wintypes.LPARAM
        result = ctypes.c_size_t()
        send(0xFFFF, 0x1A, 0, "Environment", 2, 1000, ctypes.byref(result))
