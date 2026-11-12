"""Contracts between the visual guide, CLI registration and exported HTML."""
from __future__ import annotations

import json
import re
import shlex

import pytest
from typer.main import get_command

from gai.cli import app
from gai.guide.catalog import command_catalog
from gai.guide.page import _commands, write_guide_html


def cli_commands():
    result = {}

    def visit(command, path):
        if path:
            result[" ".join(path)] = command
        for name, child in getattr(command, "commands", {}).items():
            if not getattr(child, "hidden", False):
                visit(child, [*path, name])

    visit(get_command(app), [])
    return result


@pytest.fixture(scope="module")
def catalog():
    return command_catalog(_commands())


def test_catalog_covers_cli_tree_and_parameter_contract(catalog):
    registered = cli_commands()
    entries = {c["id"]: c for c in catalog["commands"]}
    assert entries.keys() == registered.keys()
    for key, command in registered.items():
        entry = entries[key]
        assert entry["group"] in {group["id"] for group in catalog["groups"]}
        params = {p.name: p for p in command.params if not getattr(p, "hidden", False)}
        rows = {p["name"]: p for p in entry["arguments"] + entry["options"]}
        assert rows.keys() == params.keys()
        for name, row in rows.items():
            param = params[name]
            assert row["required"] == bool(param.required)
            assert row["flags"] == list(param.opts) + list(getattr(param, "secondary_opts", []))
        for child in entry["children"]:
            assert entries[child]["parent"] == key
        assert all(step["title"]["cn"] and step["title"]["en"] and
                   step["body"]["cn"] and step["body"]["en"] for step in entry["steps"])
    assert entries["branch"]["arguments"][0]["required"]
    flags = {flag for row in entries["splitflow"]["options"] for flag in row["flags"]}
    assert {"--resume", "--yes", "--review-current", "--replan", "--no-push"} <= flags


def test_all_examples_parse_without_invoking_commands(catalog):
    registered = cli_commands()
    for entry in catalog["commands"]:
        for example in entry["examples"]:
            tokens = shlex.split(example["command"])
            prefix = ["gai", *entry["id"].split()]
            # Group examples can intentionally demonstrate one of their children.
            assert tokens[:len(prefix)] == prefix
            args = tokens[1:]
            path = []
            command = get_command(app)
            while args and args[0] in getattr(command, "commands", {}):
                name = args.pop(0)
                path.append(name)
                command = command.commands[name]
            if "--help" in args:
                continue
            assert " ".join(path) in registered
            # Parsing checks options, values and required arguments; invoke is never called.
            with command.make_context(" ".join(path), args):
                pass


def test_catalog_is_bilingual_and_does_not_export_defaults(monkeypatch):
    root = get_command(app)
    secret = "private-key-must-not-appear-in-guide"
    option = next(p for p in root.commands["config"].params if p.name == "api_key")
    option.default = secret
    monkeypatch.setattr("typer.main.get_command", lambda _: root)
    catalog = command_catalog(_commands())
    assert secret not in json.dumps(catalog)
    split = next(c for c in catalog["commands"] if c["id"] == "splitflow")
    resume = next(p for p in split["options"] if p["name"] == "resume")
    assert resume["help"]["cn"] != resume["help"]["en"]
    assert any("--resume --replan" in e["command"] for e in split["examples"])


def test_embedded_catalog_escapes_html(tmp_path, monkeypatch):
    dangerous = '</script><img src=x onerror="alert(1)">'
    original = command_catalog(_commands())
    original["commands"][0]["description"]["en"] = dangerous
    monkeypatch.setattr("gai.guide.page.command_catalog", lambda _: original)
    text = write_guide_html(path=tmp_path / "guide.html").read_text(encoding="utf-8")
    assert dangerous not in text
    embedded = re.search(r'<script[^>]*id="guide-data"[^>]*>(.*?)</script>', text, re.S)
    assert embedded
    parsed = json.loads(embedded.group(1))
    assert parsed["catalog"]["commands"][0]["description"]["en"] == dangerous
    assert 'id="classic-guide"' in text and 'id="visual-guide"' in text


def test_guide_generation_does_not_run_command_callbacks(tmp_path, monkeypatch):
    root = get_command(app)

    def fail(*args, **kwargs):
        pytest.fail("Generating a guide must not run a CLI command")

    def guard(command):
        command.callback = fail
        for child in getattr(command, "commands", {}).values():
            guard(child)

    guard(root)
    monkeypatch.setattr("typer.main.get_command", lambda _: root)
    assert write_guide_html(path=tmp_path / "guide.html").is_file()
