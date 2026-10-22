"""Merge and rebase commands."""

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
from gai.common.git import (
    GitError,
    commits_ahead_of_head,
    get_current_branch,
    is_worktree_dirty,
    merge as git_merge,
    merge_abort as git_merge_abort,
    merge_continue as git_merge_continue,
    merge_in_progress,
    rebase as git_rebase,
    rebase_abort as git_rebase_abort,
    rebase_continue as git_rebase_continue,
    rebase_in_progress,
    short_status,
)
from gai.common.i18n import H

@app.command(
    "merge",
    help=H(
        "Merge another branch into HEAD, or --continue / --abort an in-progress merge.",
        "将其他分支合并进当前分支；或 --continue / --abort 进行中的合并。",
    ),
)
def merge_cmd(
    branch: Optional[str] = typer.Argument(
        None,
        help=H("Branch or ref to merge into HEAD.", "要合并进当前 HEAD 的分支或引用。"),
    ),
    no_ff: bool = typer.Option(
        False,
        "--no-ff",
        help=H(
            "Create a merge commit even for fast-forward.",
            "即使可快进也创建 merge commit。",
        ),
    ),
    continue_merge: bool = typer.Option(
        False,
        "--continue",
        help=H(
            "Continue after resolving merge conflicts.",
            "解决冲突后继续合并。",
        ),
    ),
    abort_merge: bool = typer.Option(
        False,
        "--abort",
        help=H(
            "Abort an in-progress merge and restore pre-merge state.",
            "中止进行中的合并，恢复合并前状态。",
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
    """Merge a branch into HEAD, or continue/abort an in-progress merge."""
    _start_trace(trace)
    try:
        if continue_merge and abort_merge:
            console.print(
                "[red]错误：不能同时使用 --continue 和 --abort。[/red]"
                if cn
                else "[red]Error: --continue and --abort cannot be used together.[/red]"
            )
            raise typer.Exit(code=2)
        if (continue_merge or abort_merge) and branch:
            console.print(
                "[red]错误：--continue / --abort 不要再指定分支名。[/red]"
                if cn
                else "[red]Error: do not pass a branch with --continue / --abort.[/red]"
            )
            raise typer.Exit(code=2)

        if abort_merge:
            if not merge_in_progress():
                console.print(
                    "[yellow]当前没有进行中的合并。[/yellow]"
                    if cn
                    else "[yellow]No merge in progress.[/yellow]"
                )
                raise typer.Exit(code=0)
            ask = "确定中止本次合并？" if cn else "Confirm abort this merge?"
            if not yes and not Confirm.ask(ask, default=False):
                console.print("已取消。" if cn else "Aborted.")
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在中止合并..." if cn else "Aborting merge...") + "[/bold]"):
                git_merge_abort()
            console.print(
                "[green]已中止合并。[/green]" if cn else "[green]Merge aborted.[/green]"
            )
            return

        if continue_merge:
            if not merge_in_progress():
                console.print(
                    "[yellow]当前没有进行中的合并。[/yellow]"
                    if cn
                    else "[yellow]No merge in progress.[/yellow]"
                )
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在继续合并..." if cn else "Continuing merge...") + "[/bold]"):
                git_merge_continue()
            console.print(
                "[green]合并已继续完成。[/green]" if cn else "[green]Merge continued.[/green]"
            )
            return

        if not branch:
            console.print(
                "[red]错误：请指定要合并的分支，或使用 --continue / --abort。[/red]"
                if cn
                else "[red]Error: pass a branch to merge, or use --continue / --abort.[/red]"
            )
            raise typer.Exit(code=2)

        current = get_current_branch()
        ahead = commits_ahead_of_head(branch)
        console.print(
            (f"当前分支：{current}" if cn else f"Current branch: {current}")
        )
        if ahead <= 0:
            tip = (
                f"已与 {branch} 同步，没有可合并的提交。"
                if cn
                else f"Already up to date with {branch}; nothing to merge."
            )
            console.print(f"[yellow]{tip}[/yellow]")
            raise typer.Exit(code=0)
        console.print(
            (
                f"将合并：{branch}（带来约 {ahead} 个提交）"
                if cn
                else f"Will merge: {branch} (~{ahead} commit(s))"
            )
        )
        if no_ff:
            console.print(
                "[dim]使用 --no-ff（强制生成 merge commit）[/dim]"
                if cn
                else "[dim]Using --no-ff (force merge commit)[/dim]"
            )
        _confirm_dirty_continue(chinese=cn, yes=yes, action="合并" if cn else "merge")
        ask = (
            f"确定把 {branch} 合并进 {current}？"
            if cn
            else f"Confirm merge {branch} into {current}?"
        )
        if not yes and not Confirm.ask(ask, default=False):
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)
        with console.status("[bold]" + ("正在合并..." if cn else "Merging...") + "[/bold]"):
            brought = git_merge(branch, no_ff=no_ff)
        console.print(
            f"[green]已合并 {branch}（约 {brought} 个提交）→ {current}[/green]"
            if cn
            else f"[green]Merged {branch} (~{brought} commit(s)) → {current}[/green]"
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
    "rebase",
    help=H(
        "Rebase onto another ref, or --continue / --abort an in-progress rebase.",
        "变基到另一引用；或 --continue / --abort 进行中的变基。",
    ),
)
def rebase_cmd(
    onto: Optional[str] = typer.Argument(
        None,
        help=H("Upstream ref to rebase onto (e.g. main, origin/main).", "变基目标（如 main、origin/main）。"),
    ),
    continue_rebase: bool = typer.Option(
        False,
        "--continue",
        help=H(
            "Continue after resolving rebase conflicts.",
            "解决冲突后继续变基。",
        ),
    ),
    abort_rebase: bool = typer.Option(
        False,
        "--abort",
        help=H(
            "Abort an in-progress rebase and restore the original branch.",
            "中止进行中的变基，恢复原分支。",
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
    """Rebase current branch, or continue/abort an in-progress rebase."""
    _start_trace(trace)
    try:
        if continue_rebase and abort_rebase:
            console.print(
                "[red]错误：不能同时使用 --continue 和 --abort。[/red]"
                if cn
                else "[red]Error: --continue and --abort cannot be used together.[/red]"
            )
            raise typer.Exit(code=2)
        if (continue_rebase or abort_rebase) and onto:
            console.print(
                "[red]错误：--continue / --abort 不要再指定目标分支。[/red]"
                if cn
                else "[red]Error: do not pass a ref with --continue / --abort.[/red]"
            )
            raise typer.Exit(code=2)

        if abort_rebase:
            if not rebase_in_progress():
                console.print(
                    "[yellow]当前没有进行中的变基。[/yellow]"
                    if cn
                    else "[yellow]No rebase in progress.[/yellow]"
                )
                raise typer.Exit(code=0)
            warn = (
                "将丢弃本次变基已重放的提交，回到变基前的分支。"
                if cn
                else "This discards replayed commits and restores the branch from before the rebase."
            )
            console.print(f"[yellow]{warn}[/yellow]")
            ask = "确定中止本次变基？" if cn else "Confirm abort this rebase?"
            if not yes and not Confirm.ask(ask, default=False):
                console.print("已取消。" if cn else "Aborted.")
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在中止变基..." if cn else "Aborting rebase...") + "[/bold]"):
                git_rebase_abort()
            console.print(
                "[green]已中止变基。[/green]" if cn else "[green]Rebase aborted.[/green]"
            )
            return

        if continue_rebase:
            if not rebase_in_progress():
                console.print(
                    "[yellow]当前没有进行中的变基。[/yellow]"
                    if cn
                    else "[yellow]No rebase in progress.[/yellow]"
                )
                raise typer.Exit(code=0)
            with console.status("[bold]" + ("正在继续变基..." if cn else "Continuing rebase...") + "[/bold]"):
                git_rebase_continue()
            console.print(
                "[green]变基已继续完成。[/green]" if cn else "[green]Rebase continued.[/green]"
            )
            return

        if not onto:
            console.print(
                "[red]错误：请指定变基目标，或使用 --continue / --abort。[/red]"
                if cn
                else "[red]Error: pass a ref to rebase onto, or use --continue / --abort.[/red]"
            )
            raise typer.Exit(code=2)

        current = get_current_branch()
        console.print(
            (f"当前分支：{current}" if cn else f"Current branch: {current}")
        )
        console.print(
            (f"变基到：{onto}" if cn else f"Rebase onto: {onto}")
        )
        warn = (
            "警告：rebase 会改写当前分支历史；若已推送过，之后需要 force-push（有风险）。"
            if cn
            else "Warning: rebase rewrites this branch's history; if already pushed you may need a risky force-push later."
        )
        console.print(f"[yellow]{warn}[/yellow]")
        _confirm_dirty_continue(chinese=cn, yes=yes, action="变基" if cn else "rebase")
        ask = (
            f"确定把 {current} 变基到 {onto}？"
            if cn
            else f"Confirm rebase {current} onto {onto}?"
        )
        if not yes and not Confirm.ask(ask, default=False):
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)
        with console.status("[bold]" + ("正在变基..." if cn else "Rebasing...") + "[/bold]"):
            replayed = git_rebase(onto)
        console.print(
            f"[green]已将 {current} 变基到 {onto}（重放约 {replayed} 个提交）[/green]"
            if cn
            else f"[green]Rebased {current} onto {onto} (replayed ~{replayed} commit(s))[/green]"
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


