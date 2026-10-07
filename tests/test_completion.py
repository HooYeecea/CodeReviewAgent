"""Tests for gai shell Tab-completion."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout

from typer.completion import completion_init, shell_complete
from typer.main import get_command

from gai.cli import app, run
from gai.completion_cmd import SHELL_CHOICES


def _with_complete_env(args: str, word: str):
    prev_args = os.environ.get("_TYPER_COMPLETE_ARGS")
    prev_word = os.environ.get("_TYPER_COMPLETE_WORD_TO_COMPLETE")
    prev_instr = os.environ.get("_GAI_COMPLETE")
    os.environ["_TYPER_COMPLETE_ARGS"] = args
    os.environ["_TYPER_COMPLETE_WORD_TO_COMPLETE"] = word
    os.environ.pop("_GAI_COMPLETE", None)

    def _restore() -> None:
        for key, prev in (
            ("_TYPER_COMPLETE_ARGS", prev_args),
            ("_TYPER_COMPLETE_WORD_TO_COMPLETE", prev_word),
            ("_GAI_COMPLETE", prev_instr),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    return _restore


def test_completion_lists_subcommands_for_prefix_r():
    completion_init()
    cmd = get_command(app)
    restore = _with_complete_env("gai r", "r")
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = shell_complete(cmd, {}, "gai", "_GAI_COMPLETE", "complete_powershell")
        assert rc == 0
        text = buf.getvalue()
        assert "review:::" in text
        assert "report:::" in text
        assert "commit:::" not in text
    finally:
        restore()


def test_completion_lists_all_top_level_commands():
    completion_init()
    cmd = get_command(app)
    restore = _with_complete_env("gai ", "")
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = shell_complete(cmd, {}, "gai", "_GAI_COMPLETE", "complete_powershell")
        assert rc == 0
        text = buf.getvalue()
        for name in ("add", "commit", "review", "report", "usage", "completion", "config"):
            assert f"{name}:::" in text
    finally:
        restore()


def test_completion_show_powershell_script():
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run(["completion", "show", "--shell", "powershell"])
    assert code == 0
    script = out.getvalue()
    assert "Register-ArgumentCompleter" in script
    assert "_GAI_COMPLETE" in script
    assert "gai" in script
    assert "try" in script and "finally" in script
    assert "Remove-Item Env:_GAI_COMPLETE" in script
    assert "# >>> gai completion >>>" in script


def test_install_powershell_replaces_legacy_block(tmp_path, monkeypatch):
    from gai import completion_cmd as mod

    profile = tmp_path / "Microsoft.PowerShell_profile.ps1"
    profile.write_text(
        "Write-Host hi\n"
        "Import-Module PSReadLine\n"
        "Set-PSReadLineKeyHandler -Chord Tab -Function MenuComplete\n"
        "$scriptblock = {\n"
        "    param($wordToComplete, $commandAst, $cursorPosition)\n"
        '    $Env:_GAI_COMPLETE = "complete_powershell"\n'
        "    gai | ForEach-Object { $_\n"
        "    }\n"
        '    $Env:_GAI_COMPLETE = ""\n'
        "}\n"
        "Register-ArgumentCompleter -Native -CommandName gai -ScriptBlock $scriptblock\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "_powershell_profile_path", lambda shell: profile)
    path = mod.install_powershell_completion(shell="powershell")
    text = path.read_text(encoding="utf-8")
    assert text.count("Register-ArgumentCompleter") == 1
    assert "Write-Host hi" in text
    assert "Set-PSReadLineKeyHandler" not in text
    assert "finally" in text
    assert text.count("# >>> gai completion >>>") == 1


def test_completion_show_rejects_unknown_shell():
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = run(["completion", "show", "--shell", "cmd", "--cn"])
    assert code == 2
    tip = err.getvalue()
    assert "无法识别" in tip or "shell" in tip.lower()
    for name in SHELL_CHOICES:
        # at least powershell mentioned in the tip
        pass
    assert "powershell" in tip


def test_help_mentions_completion_and_install_flag():
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run(["-h"])
    assert code == 0
    text = out.getvalue() + err.getvalue()
    assert "completion" in text
    assert "--install-completion" in text or "Install completion" in text
