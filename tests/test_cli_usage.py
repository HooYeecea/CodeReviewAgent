"""Tests for friendly CLI usage hints (typos / missing dashes)."""

from __future__ import annotations

from typer.main import get_command

from gai.cli import app, run
from gai.cli_usage import close_matches, format_usage_error


def test_close_matches_commit_typo():
    assert "commit" in close_matches("comit", ["commit", "uncommit", "config"])


def test_format_unknown_command_cn():
    root = get_command(app)

    class Exc(Exception):
        pass

    exc = Exc("No such command 'comit'.")
    tip = format_usage_error(exc, argv=["comit", "--cn"], root=root, chinese=True)
    assert "未知子命令" in tip
    assert "commit" in tip
    assert "gai commit" in tip
    assert "—" in tip
    assert "审查" in tip or "提交" in tip


def test_format_unknown_command_en_has_desc():
    root = get_command(app)

    class Exc(Exception):
        pass

    tip = format_usage_error(
        Exc("No such command 'pus'."),
        argv=["pus"],
        root=root,
        chinese=False,
    )
    assert "Correct examples" in tip
    assert "gai push" in tip
    assert "Push current branch" in tip


def test_format_unknown_option_double_dash_cn():
    root = get_command(app)
    from click.exceptions import NoSuchOption

    exc = NoSuchOption("--yess", message="No such option: --yess")
    tip = format_usage_error(
        exc, argv=["commit", "--yess", "--cn"], root=root, chinese=True
    )
    assert "未知参数" in tip
    assert "--yes" in tip
    assert "gai commit" in tip


def test_format_single_dash_long_option_cn():
    root = get_command(app)
    from click.exceptions import NoSuchOption

    exc = NoSuchOption("-yes", message="No such option: -yes")
    tip = format_usage_error(
        exc, argv=["commit", "-yes", "--cn"], root=root, chinese=True
    )
    assert "两个短横线" in tip or "--yes" in tip


def test_format_missing_dashes_extra_arg_cn():
    root = get_command(app)

    class Exc(Exception):
        pass

    exc = Exc("Got unexpected extra argument(s) (yes)")
    tip = format_usage_error(
        exc, argv=["commit", "yes", "--cn"], root=root, chinese=True
    )
    assert "多余参数" in tip
    assert "--yes" in tip or "-y" in tip


def test_run_unknown_command_returns_2(capsys):
    code = run(["comit", "--cn"])
    assert code == 2
    err = capsys.readouterr().err
    assert "未知子命令" in err or "commit" in err


def test_run_unknown_option_returns_2(capsys):
    code = run(["push", "--yess", "--cn"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--yes" in err


def test_run_missing_dashes_suggests_yes(capsys):
    code = run(["commit", "yes", "--cn"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--yes" in err
    assert "--version" not in err
