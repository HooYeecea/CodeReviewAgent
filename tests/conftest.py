"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from writing usage.jsonl into the real project tree."""
    monkeypatch.setenv("GAI_USAGE_LOG", str(tmp_path / "usage.jsonl"))
