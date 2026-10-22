"""Compatibility shim — implementation lives in ``gai.completion.cmd``."""

from __future__ import annotations

from gai.completion.cmd import (
    SHELL_CHOICES,
    completion_app,
    get_shell_completion_script,
    install_powershell_completion,
    powershell_completion_script,
)

__all__ = [
    "SHELL_CHOICES",
    "completion_app",
    "get_shell_completion_script",
    "install_powershell_completion",
    "powershell_completion_script",
]
