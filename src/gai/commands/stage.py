"""Stage / unstage / uncommit commands."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.prompt import Confirm

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
    err_console,
)
from gai.git_ops import (
    GitError,
    add as git_add,
    has_staged_changes,
    last_commit_subject,
    short_status,
    unadd as git_unadd,
    uncommit as git_uncommit,
)
from gai.help_i18n import H

@app.command(
    "add",
    help=H(
        "Stage files (wrapper around git add). Defaults to '.' when no path is given.",
        "暂存文件（包装 git add）。未指定路径时默认 git add .",
    ),
)
def add_cmd(
    paths: Optional[List[str]] = typer.Argument(
        None,
        help=H(
            "Paths to stage. Omit to run git add .",
            "要暂存的路径；省略则执行 git add .",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese messages.",
            "使用简体中文提示；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Stage files via git add."""
    _start_trace(trace)
    try:
        targets = list(paths) if paths else ["."]
        git_add(targets)
        msg = (
            f"已暂存：{' '.join(targets)}"
            if cn
            else f"Staged: {' '.join(targets)}"
        )
        console.print(f"[green]{msg}[/green]")
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "unadd",
    help=H(
        "Unstage files (undo gai add). Defaults to '.' when no path is given. Requires confirmation.",
        "撤销暂存（对应 gai add）。未指定路径时默认全部暂存区。需要确认。",
    ),
)
def unadd_cmd(
    paths: Optional[List[str]] = typer.Argument(
        None,
        help=H(
            "Paths to unstage. Omit to unstage everything (git restore --staged .).",
            "要取消暂存的路径；省略则撤销全部暂存（git restore --staged .）。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese messages.",
            "使用简体中文提示；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Unstage files via git restore --staged."""
    _start_trace(trace)
    try:
        if not has_staged_changes():
            tip = (
                "没有已暂存变更，无需撤销。"
                if cn
                else "Nothing staged; nothing to unadd."
            )
            err_console.print(f"[yellow]{tip}[/yellow]")
            raise typer.Exit(code=1)

        targets = list(paths) if paths else ["."]
        console.print(
            ("将取消暂存：" if cn else "Will unstage: ")
            + " ".join(targets)
        )
        ask = "确定撤销暂存？" if cn else "Confirm unstage?"
        if not Confirm.ask(ask, default=False):
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)

        git_unadd(targets)
        msg = (
            f"已取消暂存：{' '.join(targets)}"
            if cn
            else f"Unstaged: {' '.join(targets)}"
        )
        console.print(f"[green]{msg}[/green]")
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "uncommit",
    help=H(
        "Undo the latest commit (git reset --soft HEAD~1). Keeps changes staged. Requires confirmation.",
        "撤销最近一次提交（git reset --soft HEAD~1），改动保留在暂存区。需要确认。",
    ),
)
def uncommit_cmd(
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese messages.",
            "使用简体中文提示；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Undo the latest commit with a soft reset."""
    _start_trace(trace)
    try:
        subject = last_commit_subject()
        if subject is None:
            tip = (
                "没有可撤销的提交。"
                if cn
                else "No commit to undo."
            )
            err_console.print(f"[red]{tip}[/red]")
            raise typer.Exit(code=1)

        console.print(
            ("将撤销提交：" if cn else "Will undo commit: ")
            + subject
        )
        tip = (
            "说明：使用 soft reset，文件改动会保留在暂存区。"
            if cn
            else "Note: soft reset — changes stay staged."
        )
        console.print(f"[dim]{tip}[/dim]")
        ask = "确定撤销该提交？" if cn else "Confirm undo commit?"
        if not Confirm.ask(ask, default=False):
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)

        undone = git_uncommit()
        msg = (
            f"已撤销提交：{undone}"
            if cn
            else f"Undid commit: {undone}"
        )
        console.print(f"[green]{msg}[/green]")
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)
