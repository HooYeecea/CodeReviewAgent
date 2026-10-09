"""gai CLI entrypoint: shared app + command registration + run()."""

from __future__ import annotations

import sys
import time

import typer

from gai.cli_common import (
    _version_callback,
    app,
    err_console,
)
from gai.cli_usage import format_usage_error, want_chinese
from gai.command_history import maybe_record_command
from gai.help_i18n import H

# Register subcommands on the shared ``app``.
from gai.commands import insight as _insight  # noqa: F401
from gai.commands import setup as _setup  # noqa: F401
from gai.commands import ship as _ship  # noqa: F401
from gai.commands import stage as _stage  # noqa: F401
from gai.commands import sync as _sync  # noqa: F401
from gai.commands.setup import _attach_profile_balances  # noqa: F401

from gai.llm.balance import fetch_balance  # tests monkeypatch gai.cli.fetch_balance


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help=H("Show version and exit.", "显示版本并退出。"),
        callback=_version_callback,
        is_eager=True,
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Show help in Simplified Chinese (use with -h/--help). "
            "Also enables Chinese output on subcommands that support it.",
            "与 -h/--help 联用时显示中文帮助；在支持的子命令中同时启用中文输出。",
        ),
        is_eager=True,
    ),
) -> None:
    """gai — AI-assisted local git commit & code review."""
    _ = cn


def run(argv: list[str] | None = None) -> int:
    """CLI entrypoint with friendly usage-error hints (typos / missing dashes)."""
    from typer.main import get_command

    args = list(sys.argv[1:] if argv is None else argv)
    chinese = want_chinese(args)
    root = get_command(app)
    started = time.perf_counter()
    code = 1

    def _exit_code(exc: BaseException) -> int | None:
        if type(exc).__name__ == "Exit":
            exit_code = getattr(exc, "exit_code", 0)
            return int(exit_code) if exit_code is not None else 0
        if isinstance(exc, typer.Exit):
            exit_code = getattr(exc, "exit_code", 0)
            return int(exit_code) if exit_code is not None else 0
        return None

    def _is_usage_error(exc: BaseException) -> bool:
        name = type(exc).__name__
        if name in {
            "UsageError",
            "NoSuchOption",
            "NoSuchCommand",
            "BadOptionUsage",
            "BadArgumentUsage",
            "BadParameter",
        }:
            return True
        try:
            import click

            return isinstance(exc, click.ClickException) and type(exc).__name__ != "Exit"
        except Exception:
            return False

    try:
        try:
            rv = root.main(args=args, prog_name="gai", standalone_mode=False)
            code = int(rv) if isinstance(rv, int) else 0
            return code
        except BaseException as exc:
            if isinstance(exc, SystemExit):
                exit_code = exc.code
                if exit_code is None:
                    code = 0
                elif isinstance(exit_code, int):
                    code = exit_code
                else:
                    code = 1
                return code
            mapped = _exit_code(exc)
            if mapped is not None:
                code = mapped
                return code
            if type(exc).__name__ == "Abort":
                tip = "\n已取消。" if chinese else "\nAborted."
                err_console.print(tip)
                code = 130
                return code
            if _is_usage_error(exc):
                tip = format_usage_error(exc, argv=args, root=root, chinese=chinese)
                label = "用法错误：" if chinese else "Usage:"
                err_console.print(f"[red]{label}[/red]")
                err_console.print(tip)
                code = 2
                return code
            raise
    finally:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        maybe_record_command(args, exit_code=code, duration_ms=duration_ms)


if __name__ == "__main__":
    raise SystemExit(run())
