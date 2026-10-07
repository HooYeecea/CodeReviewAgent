"""Multi-profile LLM config: env indices + file profiles + switch."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import gai.config as config


@pytest.fixture
def cfg_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    conf_dir = tmp_path / ".gai"
    conf_dir.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", conf_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", conf_dir / "config.toml")
    # Clear relevant env so tests are isolated.
    for key in list(os.environ):
        if key.startswith("GAI_") or key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
            monkeypatch.delenv(key, raising=False)
    return conf_dir


def test_unnumbered_env_is_profile_0(cfg_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAI_API_KEY", "sk-zero-abcdefgh")
    monkeypatch.setenv("GAI_BASE_URL", "https://api.zero.test/v1")
    monkeypatch.setenv("GAI_MODEL", "zero-model")

    s = config.load_settings()
    assert s.profile == "0"
    assert s.api_key == "sk-zero-abcdefgh"
    assert s.base_url == "https://api.zero.test/v1"
    assert s.model == "zero-model"

    rows = config.list_profiles()
    assert len(rows) == 1
    assert rows[0].name == "0"
    assert rows[0].active
    assert "env" in rows[0].sources


def test_numbered_env_profiles_and_switch(
    cfg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAI_API_KEY", "sk-zero-aaaaaaaa")
    monkeypatch.setenv("GAI_API_KEY1", "sk-one-bbbbbbbb")
    monkeypatch.setenv("GAI_BASE_URL1", "https://api.one.test/v1")
    monkeypatch.setenv("GAI_MODEL1", "one-model")

    s0 = config.load_settings()
    assert s0.profile == "0"
    assert s0.api_key == "sk-zero-aaaaaaaa"

    monkeypatch.setenv("GAI_PROFILE", "1")
    s1 = config.load_settings()
    assert s1.profile == "1"
    assert s1.api_key == "sk-one-bbbbbbbb"
    assert s1.base_url == "https://api.one.test/v1"
    assert s1.model == "one-model"

    names = [p.name for p in config.list_profiles()]
    assert names == ["0", "1"]


def test_file_current_and_named_profile(
    cfg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.save_settings(
        api_key="sk-file-00000000",
        base_url="https://api.file0.test/v1",
        model="file-zero",
        profile="0",
        set_current="0",
    )
    config.save_settings(
        api_key="sk-deep-11111111",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        profile="deepseek",
    )

    s = config.load_settings()
    assert s.profile == "0"
    assert s.api_key == "sk-file-00000000"

    config.save_settings(set_current="deepseek")
    s2 = config.load_settings()
    assert s2.profile == "deepseek"
    assert s2.api_key == "sk-deep-11111111"
    assert s2.model == "deepseek-chat"


def test_env_overrides_file_for_same_profile(
    cfg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.save_settings(
        api_key="sk-file-onlyyyyy",
        base_url="https://api.file.test/v1",
        model="file-model",
        profile="0",
        set_current="0",
    )
    monkeypatch.setenv("GAI_API_KEY", "sk-env-wins-zzzz")
    monkeypatch.setenv("GAI_MODEL", "env-model")

    s = config.load_settings()
    assert s.api_key == "sk-env-wins-zzzz"
    assert s.model == "env-model"
    # base_url only in file → keep file
    assert s.base_url == "https://api.file.test/v1"


def test_legacy_flat_toml_reads_as_profile_0(cfg_home: Path) -> None:
    config.CONFIG_FILE.write_text(
        "\n".join(
            [
                "[llm]",
                'api_key = "sk-legacy-keyyyyy"',
                'base_url = "https://api.legacy.test/v1"',
                'model = "legacy-model"',
                "timeout = 30",
                "",
                "[review]",
                "max_diff_chars = 1000",
                "ignore_patterns = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    s = config.load_settings()
    assert s.profile == "0"
    assert s.api_key == "sk-legacy-keyyyyy"
    assert s.model == "legacy-model"
    assert s.timeout == 30.0


def test_mask_and_summary(cfg_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAI_API_KEY", "sk-abcdefghijklmnop")
    s = config.load_settings()
    summary = config.settings_summary(s)
    assert summary["profile"] == "0"
    assert summary["api_key"] == "sk-a...mnop"
    assert "sk-abcdefghijklmnop" not in summary["api_key"]


def test_profiles_overview_counts_and_current(
    cfg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAI_API_KEY", "sk-zero-aaaaaaaa")
    monkeypatch.setenv("GAI_API_KEY1", "sk-one-bbbbbbbb")
    monkeypatch.setenv("GAI_PROFILE", "1")
    text = config.format_profiles_overview(chinese=True)
    assert "已配置 API Key：2 个" in text
    assert "当前使用：编号 1" in text
    assert "余额：" not in text


def test_attach_balance_field_per_profile(
    cfg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAI_API_KEY", "sk-test-xxxxxxxx")
    monkeypatch.setenv("GAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("GAI_API_KEY1", "sk-ds-yyyyyyyyyy")
    monkeypatch.setenv("GAI_BASE_URL1", "https://api.deepseek.com/v1")
    from gai.cli import _attach_profile_balances
    from gai.llm.balance import BalanceResult
    from gai.llm import balance as balance_mod

    def fake_fetch(settings):
        provider = balance_mod.detect_provider(settings.base_url)
        if not provider.supports_balance:
            return BalanceResult(supported=False, provider=provider, model=settings.model)
        return BalanceResult(
            supported=True,
            provider=provider,
            model=settings.model,
            items=[balance_mod.BalanceItem(currency="CNY", total="9.40")],
        )

    monkeypatch.setattr(balance_mod, "fetch_balance", fake_fetch)
    monkeypatch.setattr("gai.cli.fetch_balance", fake_fetch)
    rows = config.profiles_summary()
    out = _attach_profile_balances(rows, chinese=True)
    by_id = {row["profile"]: row["balance"] for row in out}
    assert by_id["0"] == "该厂商不提供余额查询"
    assert "9.40" in by_id["1"]
