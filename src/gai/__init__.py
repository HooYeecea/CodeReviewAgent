"""gai — local Git commit & code review agent."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gai")
except PackageNotFoundError:  # pragma: no cover - editable/uninstalled fallback
    __version__ = "0.1.0"
