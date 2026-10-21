"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_local_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from writing local usage/history into the real project tree.

    Global paths (``~/.gai``) are left alone so tests that monkeypatch
    ``CONFIG_DIR`` / merge helpers keep working; those tests isolate globals
    themselves.
    """
    monkeypatch.setenv("GAI_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("GAI_HISTORY_LOG", str(tmp_path / "commands.jsonl"))
