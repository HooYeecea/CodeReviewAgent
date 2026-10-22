"""Branch, switch, and stash commands."""

from __future__ import annotations

from typing import Optional

import typer
from rich.prompt import Confirm, Prompt

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _confirm_dirty_continue,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
    err_console,
)
from gai.git_ops import (
    GitError,
    create_branch as git_create_branch,
    get_current_branch,
    is_worktree_dirty,
    list_local_branches,
    short_status,
    stash_list as git_stash_list,
    stash_pop as git_stash_pop,
    stash_push as git_stash_push,
    switch_branch as git_switch,
)
from gai.help_i18n import H

@app.command(
    "branch",
    help=H(
        "Create a new branch without checking it out.",
        "创建新分支但不签出（仍停留在当前分支）。",
    ),
)
def branch_cmd(
    name: str = typer.Argument(
        ...,
        help=H("Name of the branch to create.", "要创建的分支名。"),
    ),
    start_point: Optional[str] = typer.Argument(
        None,
        help=H(
            "Optional start point (commit/branch; default: HEAD).",
            "可选起点（提交/分支；默认当前 HEAD）。",
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation.", "跳过交互确认。"),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese prompts.",
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
    """Create a branch at HEAD (or start_point) without switching to it."""
    _start_trace(trace)
    try:
        current = get_current_branch()
        console.print(
            (f"当前分支：{current}" if cn else f"Current branch: {current}")
        )
        if start_point:
            console.print(
                (
                    f"将创建分支：{name}（起点 {start_point}），不切换过去"
                    if cn
                    else f"Will create branch: {name} (from {start_point}), without switching"
                )
            )
        else:
            console.print(
                (
                    f"将创建分支：{name}（基于当前 HEAD），不切换过去"
                    if cn
                    else f"Will create branch: {name} (from HEAD), without switching"
                )
            )
        tip = (
            "需要签出请用：gai switch <name> 或 gai switch -c <name>"
            if cn
            else "To check it out: gai switch <name> or gai switch -c <name>"
        )
        console.print(f"[dim]{tip}[/dim]")
        ask = (
            f"确定创建分支 {name}？"
            if cn
            else f"Confirm create branch {name}?"
        )
        if not yes and not Confirm.ask(ask, default=True):
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)
        with console.status(
            "[bold]" + ("正在创建分支..." if cn else "Creating branch...") + "[/bold]"
        ):
            created = git_create_branch(name, start_point=start_point)
        still = get_current_branch()
        console.print(
            f"[green]已创建分支 {created}；仍在 {still}[/green]"
            if cn
            else f"[green]Created branch {created}; still on {still}[/green]"
        )
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
    "switch",
    help=H(
        "Switch branches (warns when the working tree is dirty).",
        "切换分支（工作区有未提交改动时会警告）。",
    ),
)
def switch_cmd(
    branch: str = typer.Argument(
        ...,
        help=H("Branch to switch to.", "要切换到的分支名。"),
    ),
    create: bool = typer.Option(
        False,
        "--create",
        "-c",
        help=H("Create the branch, then switch to it.", "创建分支并切换过去。"),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation when dirty.", "脏工作区时跳过交互确认。"),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese prompts.",
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
    """Switch (or create+switch) branches with dirty-worktree guards."""
    _start_trace(trace)
    try:
        current = get_current_branch()
        branches = list_local_branches()
        action = "创建并切换" if (cn and create) else ("create+switch" if create else ("切换" if cn else "switch"))
        console.print(
            (f"当前分支：{current}" if cn else f"Current branch: {current}")
        )
        if create:
            console.print(
                (f"将创建并切换到：{branch}" if cn else f"Will create and switch to: {branch}")
            )
        else:
            console.print(
                (f"将切换到：{branch}" if cn else f"Will switch to: {branch}")
            )
            if branch not in branches and not create:
                # Still allow remote-tracking / other refs via git switch.
                console.print(
                    f"[dim]本地分支列表未直接看到 {branch}，将交给 git switch 解析。[/dim]"
                    if cn
                    else f"[dim]{branch} not in local branch list; git switch will resolve it.[/dim]"
                )
        _confirm_dirty_continue(chinese=cn, yes=yes, action=action)
        if not yes and not create:
            ask = (
                f"确定切换到 {branch}？"
                if cn
                else f"Confirm switch to {branch}?"
            )
            if not Confirm.ask(ask, default=True):
                console.print("已取消。" if cn else "Aborted.")
                raise typer.Exit(code=0)
        with console.status("[bold]" + ("正在切换..." if cn else "Switching...") + "[/bold]"):
            landed = git_switch(branch, create=create)
        console.print(
            f"[green]已切换到 {landed}[/green]"
            if cn
            else f"[green]Switched to {landed}[/green]"
        )
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
    "stash",
    help=H(
        "Stash local changes, or pop the latest stash with --pop.",
        "暂存本地改动；加 --pop 弹出最近一条 stash。",
    ),
)
def stash_cmd(
    pop: bool = typer.Option(
        False,
        "--pop",
        help=H("Pop the latest stash entry.", "弹出最近一条 stash。"),
    ),
    message: Optional[str] = typer.Option(
        None,
        "--message",
        "-m",
        help=H("Optional stash message (push only).", "可选 stash 说明（仅 push）。"),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation.", "跳过交互确认。"),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese prompts.",
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
    """Stash push (default) or stash pop."""
    _start_trace(trace)
    try:
        if pop:
            entries = git_stash_list()
            if not entries:
                tip = "没有可弹出的 stash。" if cn else "No stash entries to pop."
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            console.print(
                (f"将弹出：{entries[0]}" if cn else f"Will pop: {entries[0]}")
            )
            ask = "确定弹出该 stash？" if cn else "Confirm stash pop?"
            if not yes and not Confirm.ask(ask, default=False):
                console.print("已取消。" if cn else "Aborted.")
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在弹出 stash..." if cn else "Popping stash...") + "[/bold]"):
                summary = git_stash_pop()
            console.print(f"[green]{summary}[/green]")
        else:
            if not is_worktree_dirty():
                tip = "工作区干净，没有可 stash 的改动。" if cn else "Working tree clean; nothing to stash."
                console.print(f"[yellow]{tip}[/yellow]")
                raise typer.Exit(code=0)
            status_text = short_status()
            if status_text:
                console.print(f"[dim]{status_text}[/dim]")
            ask = "确定 stash 当前改动？" if cn else "Confirm stash current changes?"
            if not yes and not Confirm.ask(ask, default=False):
                console.print("已取消。" if cn else "Aborted.")
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在 stash..." if cn else "Stashing...") + "[/bold]"):
                summary = git_stash_push(message=message)
            console.print(f"[green]{summary}[/green]")
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
