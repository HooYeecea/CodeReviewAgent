"""GUI preview/apply boundaries; all files, environment and registry are isolated."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import threading
import tomllib
import sys
from types import SimpleNamespace

import httpx
import pytest

from gai.common import config
from gai.setup.config_store import write_config
from gai.setup.editor import ConfigEditor
from gai.setup.gui import ConfigServer
from gai.setup.environment import UserEnvironment


class Registry:
    available = True

    def __init__(self):
        self.user = {}
        self.machine = {}
        self.writes = []

    def read(self, *, machine=False):
        return deepcopy(self.machine if machine else self.user)

    def expanded(self, record):
        return record[0]

    def write(self, changes):
        self.writes.append(changes)
        for name, value in changes.items():
            if value is None:
                self.user.pop(name, None)
            else:
                self.user[name] = (value, 1)


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "personal")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "personal" / "config.toml")
    project = tmp_path / "repo"
    project.mkdir()
    return ConfigEditor(project_root=project, environ={}, registry=Registry())


def save(editor, payload):
    preview = editor.preview(payload)
    editor.apply(preview["ticket"])
    return preview


def test_preview_is_read_only_secrets_redacted_and_ticket_one_shot(editor):
    payload = {"target": "personal", "fields": {"api_key": "SECRET_API_KEY", "model": "new-model"}}
    preview = editor.preview(payload)
    assert not editor.path.exists()
    assert "SECRET_API_KEY" not in json.dumps(preview)
    editor.apply(preview["ticket"])
    assert config._load_toml()["llm"]["profiles"]["0"]["api_key"] == "SECRET_API_KEY"
    assert "SECRET_API_KEY" not in json.dumps(editor.state())
    with pytest.raises(ValueError, match="失效"):
        editor.apply(preview["ticket"])


def test_masked_key_is_never_written_back_and_newline_rules_roundtrip(editor):
    save(editor, {"target": "personal", "fields": {"api_key": "KEEP_ME"}})
    save(editor, {"target": "personal", "fields": {"model": "another", "rules": ['quote " newline\n tab\t']}})
    cfg = config._load_toml()
    assert cfg["llm"]["profiles"]["0"]["api_key"] == "KEEP_ME"
    assert cfg["review"]["rules"] == ['quote " newline\n tab\t']


def test_clear_legacy_key_and_preserve_unknown_fields(editor):
    write_config(editor.path, {"llm": {"api_key": "old", "model": "old-model", "custom": True,
                  "profiles": {"1": {"model": "other", "vendor_setting": "preserve"}}},
                  "review": {"fail_on": "critical", "ignore_patterns": [], "require_complete": True}})
    save(editor, {"target": "personal", "fields": {"api_key": "", "model": "new"}})
    cfg = config._load_toml()
    assert "api_key" not in cfg["llm"]
    assert cfg["llm"]["profiles"]["0"]["api_key"] == ""
    assert cfg["llm"]["profiles"]["1"]["vendor_setting"] == "preserve"
    assert cfg["llm"]["custom"] is True
    assert cfg["review"]["fail_on"] == "critical"


def test_cli_save_retains_policy_and_does_not_copy_overrides(editor, monkeypatch):
    write_config(editor.path, {"review": {"ignore_patterns": [], "fail_on": "critical",
                                        "require_complete": True, "rules": ["检查边界"]}})
    monkeypatch.setenv("GAI_MAX_DIFF_CHARS", "999999")
    config.save_settings(model="new")
    cfg = config._load_toml()
    assert cfg["review"]["ignore_patterns"] == []
    assert cfg["review"]["rules"] == ["检查边界"]
    assert cfg["review"]["fail_on"] == "critical"
    assert cfg["review"]["require_complete"] is True
    assert cfg["review"]["max_diff_chars"] == config.DEFAULT_MAX_DIFF_CHARS


def test_personal_save_shows_environment_override(editor):
    editor.env["GAI_MODEL"] = "env-model"
    preview = save(editor, {"target": "personal", "fields": {"model": "file-model"}})
    assert preview["after"]["model"] == {"value": "env-model", "source": "环境变量 · GAI_MODEL"}
    assert editor.state()["profiles"]["0"]["model"] == "file-model"


def test_project_deletion_shows_personal_fallback(editor):
    save(editor, {"target": "personal", "fields": {"fail_on": "warning"}})
    save(editor, {"target": "project", "fields": {"fail_on": "critical"}})
    preview = save(editor, {"target": "project", "fields": {"fail_on": None}})
    assert preview["after"]["fail_on"] == {"value": "warning", "source": "个人配置"}
    assert "fail_on" not in tomllib.loads(editor.project_path.read_text())["review"]
    assert sorted(p.name for p in editor.project_path.parent.iterdir()) == [".gai.toml"]
    with pytest.raises(ValueError):
        editor.preview({"target": "project", "fields": {"api_key": "NO"}})


def test_environment_delete_falls_back_to_alias_then_file(editor):
    save(editor, {"target": "personal", "fields": {"base_url": "https://file.test/v1"}})
    editor.env.update(GAI_BASE_URL="https://gai.test", OPENAI_BASE_URL="https://alias.test")
    p = save(editor, {"target": "environment", "scope": "process", "name": "GAI_BASE_URL", "value": None})
    assert p["fallback"] == {"value": "https://alias.test", "source": "环境变量 · OPENAI_BASE_URL"}
    p = save(editor, {"target": "environment", "scope": "process", "name": "OPENAI_BASE_URL", "value": None})
    assert p["fallback"] == {"value": "https://file.test/v1", "source": "个人配置 · 0"}
    assert editor.registry.writes == []


def test_user_deletion_retains_machine_setting(editor):
    editor.registry.user["GAI_MODEL"] = ("user", 1)
    editor.registry.machine["GAI_MODEL"] = ("machine", 1)
    editor.env["GAI_MODEL"] = "user"
    preview = editor.preview({"target": "environment", "scope": "user", "name": "GAI_MODEL", "value": None})
    assert preview["fallback"]["value"] == "machine"
    assert "系统级" in preview["fallback"]["note"]
    assert editor.registry.user["GAI_MODEL"][0] == "user"
    editor.apply(preview["ticket"])
    assert editor.env["GAI_MODEL"] == "machine"
    assert "GAI_MODEL" not in editor.registry.user
    assert editor.registry.machine["GAI_MODEL"][0] == "machine"


def test_numbered_profile_and_named_profile_precedence(editor):
    save(editor, {"target": "personal", "profile": "2", "fields": {"model": "second"}})
    editor.env["GAI_MODEL2"] = "second-env"
    preview = editor.preview({"target": "environment", "scope": "process", "name": "GAI_MODEL2", "value": None})
    assert preview["fallback"]["value"] == "second"
    assert preview["after"]["profile"]["value"] == "0"
    save(editor, {"target": "personal", "profile": "named", "fields": {"model": "named-model", "current": "named"}})
    editor.env["GAI_MODEL"] = "zero-only"
    assert editor.state()["effective"]["model"]["value"] == "named-model"


@pytest.mark.parametrize("fields", [{"timeout": 0}, {"timeout": float("nan")}, {"max_diff_chars": True},
    {"fail_on": "wrong"}, {"require_complete": "yes"}, {"rules": "not a list"},
    {"base_url": "https://user:secret@test/v1"}])
def test_invalid_saved_values_rejected_even_when_overridden(editor, fields):
    editor.env.update(GAI_TIMEOUT="60", GAI_MAX_DIFF_CHARS="80000")
    with pytest.raises((ValueError, RuntimeError)):
        editor.preview({"target": "personal", "fields": fields})
    assert not editor.path.exists()


@pytest.mark.parametrize("name,value", [("PATH", "bad"), ("GAI_UNKNOWN", "bad"), ("GAI_MODEL0", "bad"),
    ("GAI_GIT_TIMEOUT", "nan"), ("GAI_TIMEOUT", "0"), ("GAI_MAX_DIFF_CHARS", "-1"),
    ("GAI_MODEL", ""), ("GAI_MODEL", "x\x00y")])
def test_environment_allowlist_and_validation(editor, name, value):
    with pytest.raises(ValueError):
        editor.preview({"target": "environment", "scope": "user", "name": name, "value": value})
    assert editor.registry.writes == []


@pytest.mark.parametrize("mutation", ["file", "env", "registry", "project"])
def test_stale_preview_cannot_overwrite_new_changes(editor, mutation):
    preview = editor.preview({"target": "personal", "fields": {"model": "new"}})
    if mutation == "file":
        write_config(editor.path, {"llm": {"model": "external"}})
    elif mutation == "env":
        editor.env["GAI_MODEL"] = "external"
    elif mutation == "registry":
        editor.registry.user["GAI_MODEL"] = ("external", 1)
    else:
        write_config(editor.project_path, {"review": {"fail_on": "critical"}})
    with pytest.raises(ValueError, match="其他操作"):
        editor.apply(preview["ticket"])


def test_expired_preview_and_registry_failure(editor, monkeypatch):
    preview = editor.preview({"target": "environment", "scope": "user", "name": "GAI_MODEL", "value": "new"})
    editor.pending["expires"] = 0
    with pytest.raises(ValueError, match="失效"):
        editor.apply(preview["ticket"])
    preview = editor.preview({"target": "environment", "scope": "user", "name": "GAI_MODEL", "value": "new"})
    def fail(changes):
        raise OSError("denied")
    monkeypatch.setattr(editor.registry, "write", fail)
    with pytest.raises(OSError):
        editor.apply(preview["ticket"])
    assert "GAI_MODEL" not in editor.env


def test_non_windows_user_environment_disabled(editor):
    editor.registry.available = False
    assert not editor.state()["user_environment_supported"]
    with pytest.raises(ValueError, match="不支持"):
        editor.preview({"target": "environment", "scope": "user", "name": "GAI_MODEL", "value": "new"})
    save(editor, {"target": "environment", "scope": "process", "name": "GAI_MODEL", "value": "new"})


def test_atomic_write_failure_keeps_original_file(editor, monkeypatch):
    save(editor, {"target": "personal", "fields": {"model": "old"}})
    old = editor.path.read_bytes()
    preview = editor.preview({"target": "personal", "fields": {"model": "new"}})
    def fail(*args):
        raise OSError("disk error")
    monkeypatch.setattr("gai.setup.config_store.os.replace", fail)
    with pytest.raises(OSError):
        editor.apply(preview["ticket"])
    assert editor.path.read_bytes() == old
    assert not list(editor.path.parent.glob("*.tmp"))


def test_connection_uses_preview_not_disk_and_no_secrets_in_errors(editor, monkeypatch):
    preview = editor.preview({"target": "personal", "fields": {"api_key": "DO_NOT_LEAK", "base_url": "https://example.test/v1"}})
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(401, text="DO_NOT_LEAK"))
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=transport, **kw))
    result = editor.test_connection(preview["ticket"])
    assert "401" in result["message"] and "DO_NOT_LEAK" not in json.dumps(result)
    assert str(calls[0].url) == "https://example.test/v1/models"
    assert calls[0].headers["Authorization"] == "Bearer DO_NOT_LEAK"
    assert calls[0].method == "GET"
    assert not editor.path.exists()


def test_local_http_auth_origin_preview_and_apply(editor):
    with ConfigServer(editor) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=server.origin, trust_env=False) as client:
                assert client.get("/api/state").status_code == 403
                headers = {"X-Gai-Token": server.token, "Origin": server.origin}
                assert client.get("/api/state", headers={**headers, "Origin": "https://evil.test"}).status_code == 403
                assert client.get("/api/state", headers={**headers, "Host": "evil.test"}).status_code == 403
                assert client.get("/config.toml").status_code == 404
                page = client.get("/")
                assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
                assert "no-store" == page.headers["Cache-Control"]
                assert client.get("/config.js").status_code == 200
                assert client.get("/config.css").status_code == 200
                assert client.get("/api/state", headers=headers).status_code == 200
                assert client.post("/api/preview", headers=headers, content="{}").status_code == 415
                preview = client.post("/api/preview", headers=headers,
                                      json={"target": "personal", "fields": {"model": "via-http"}}).json()
                assert not editor.path.exists()
                saved = client.post("/api/apply", headers=headers, json={"ticket": preview["ticket"]})
                assert saved.status_code == 200
                assert saved.json()["effective"]["model"]["value"] == "via-http"
                assert client.post("/api/apply", headers=headers, json={"ticket": preview["ticket"]}).status_code == 400
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_cli_gui_dispatch_and_conflicting_options(monkeypatch):
    from typer.testing import CliRunner
    from gai.cli import app
    calls = []
    monkeypatch.setattr("gai.setup.gui.serve_config", lambda **kw: calls.append(kw))
    runner = CliRunner()
    assert runner.invoke(app, ["config", "--gui", "--no-open"]).exit_code == 0
    assert calls == [{"open_browser": False}]
    assert runner.invoke(app, ["config", "--gui", "--model", "bad"]).exit_code == 2
    assert runner.invoke(app, ["config", "--no-open"]).exit_code == 2


def test_ui_javascript_syntax():
    if not shutil.which("node"):
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--check", str(root / "src/gai/static/config.js")], check=True, capture_output=True)


def test_registry_adapter_uses_current_user_and_restores_partial_failure(monkeypatch):
    user = {"GAI_MODEL": ("old", 2), "PATH": ("never-touch", 1)}
    machine = {"GAI_MODEL": ("system", 1)}
    writes = []
    class Handle:
        def __init__(self, root):
            self.root = root
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def table(handle):
        return user if handle.root == "user" else machine
    def set_value(handle, name, reserved, kind, value):
        writes.append((handle.root, name))
        assert handle.root == "user"
        if name == "GAI_TIMEOUT":
            raise OSError("simulated registry failure")
        table(handle)[name] = (value, kind)
    def delete(handle, name):
        assert handle.root == "user"
        if name not in table(handle):
            raise FileNotFoundError()
        del table(handle)[name]
    mock = SimpleNamespace(HKEY_CURRENT_USER="user", HKEY_LOCAL_MACHINE="machine",
        KEY_READ=1, KEY_SET_VALUE=2, REG_SZ=1, REG_EXPAND_SZ=2,
        OpenKey=lambda root, *args: Handle(root), CreateKeyEx=lambda root, *args: Handle(root),
        QueryInfoKey=lambda handle: (0, len(table(handle)), 0),
        EnumValue=lambda handle, index: (lambda item: (item[0], *item[1]))(list(table(handle).items())[index]),
        SetValueEx=set_value, DeleteValue=delete, ExpandEnvironmentStrings=lambda value: value.replace("%DEMO%", "expanded"))
    monkeypatch.setitem(sys.modules, "winreg", mock)
    registry = UserEnvironment()
    registry.available = True
    monkeypatch.setattr(registry, "broadcast", lambda: None)
    assert "PATH" not in registry.read()
    assert registry.expanded(("%DEMO%", 2)) == "expanded"
    with pytest.raises(OSError):
        registry.write({"GAI_MODEL": "new", "GAI_TIMEOUT": "10"})
    assert user["GAI_MODEL"] == ("old", 2)
    assert machine["GAI_MODEL"] == ("system", 1)
    assert user["PATH"] == ("never-touch", 1)
    registry.write({"GAI_MODEL": None})
    assert "GAI_MODEL" not in user
    with pytest.raises(ValueError):
        registry.write({"PATH": "bad"})
    assert all(name != "PATH" for _, name in writes)
