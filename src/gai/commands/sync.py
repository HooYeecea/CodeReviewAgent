"""Push, pull, merge, rebase, branch, switch, stash."""

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
    NothingToPull,
    NothingToPush,
    check_sync,
    commits_ahead_of_head,
    create_branch as git_create_branch,
    get_current_branch,
    is_worktree_dirty,
    list_local_branches,
    merge as git_merge,
    merge_abort as git_merge_abort,
    merge_continue as git_merge_continue,
    merge_in_progress,
    plan_push,
    pull as git_pull,
    push as git_push,
    rebase as git_rebase,
    rebase_abort as git_rebase_abort,
    rebase_continue as git_rebase_continue,
    rebase_in_progress,
    short_status,
    stash_list as git_stash_list,
    stash_pop as git_stash_pop,
    stash_push as git_stash_push,
    switch_branch as git_switch,
)
from gai.help_i18n import H

def _do_push(
    *,
    remote: str | None = None,
    yes: bool = False,
    chinese: bool = False,
    set_upstream: bool | None = None,
) -> None:
    plan = plan_push(remote=remote, set_upstream=set_upstream)
    status = "正在检查远程同步状态..." if chinese else "Checking remote sync status..."
    with console.status(f"[bold]{status}[/bold]"):
        sync = check_sync(remote=plan.remote, do_fetch=True)

    if sync.ahead <= 0:
        tip = (
            f"没有可推送的内容：本地与 {plan.remote}/{plan.branch} 已同步。"
            if chinese
            else f"Nothing to push: local is up to date with {plan.remote}/{plan.branch}."
        )
        console.print(f"[yellow]{tip}[/yellow]")
        raise typer.Exit(code=0)

    ahead_tip = (
        f"待推送提交数：{sync.ahead}"
        if chinese
        else f"Commits to push: {sync.ahead}"
    )
    console.print(f"[dim]{ahead_tip}[/dim]")
    console.print(f"[bold]{'将执行' if chinese else 'Will run'}:[/bold] {plan.describe()}")
    if plan.set_upstream:
        tip = (
            f"分支 {plan.branch} 尚无上游，将设置跟踪 {plan.remote}/{plan.branch}。"
            if chinese
            else f"Branch '{plan.branch}' has no upstream; will set {plan.remote}/{plan.branch}."
        )
        console.print(f"[dim]{tip}[/dim]")

    ask = "确认推送到远程？" if chinese else "Push to remote?"
    if not yes and not Confirm.ask(ask, default=True):
        console.print("已取消推送。" if chinese else "Push aborted.")
        raise typer.Exit(code=0)

    push_status = "正在推送..." if chinese else "Pushing..."
    with console.status(f"[bold]{push_status}[/bold]"):
        try:
            git_push(remote=remote, set_upstream=set_upstream, check=sync)
        except NothingToPush as exc:
            tip = (
                f"没有可推送的内容：{exc}"
                if chinese
                else f"Nothing to push: {exc}"
            )
            console.print(f"[yellow]{tip}[/yellow]")
            raise typer.Exit(code=0) from exc

    done = (
        f"已推送 {sync.ahead} 个提交：{plan.remote}/{plan.branch}"
        if chinese
        else f"Pushed {sync.ahead} commit(s): {plan.remote}/{plan.branch}"
    )
    console.print(f"[green]{done}[/green]")


def _do_pull(
    *,
    remote: str | None = None,
    yes: bool = False,
    chinese: bool = False,
    rebase: bool | None = None,
) -> None:
    status = "正在检查远程是否有可拉取内容..." if chinese else "Checking remote for updates..."
    with console.status(f"[bold]{status}[/bold]"):
        sync = check_sync(remote=remote, do_fetch=True)

    if sync.behind <= 0:
        tip = (
            f"没有可拉取的内容：已与 {sync.remote}/{sync.branch} 同步。"
            if chinese
            else f"Nothing to pull: already up to date with {sync.remote}/{sync.branch}."
        )
        console.print(f"[yellow]{tip}[/yellow]")
        raise typer.Exit(code=0)

    behind_tip = (
        f"待拉取提交数：{sync.behind}（{sync.remote}/{sync.branch}）"
        if chinese
        else f"Commits to pull: {sync.behind} ({sync.remote}/{sync.branch})"
    )
    console.print(f"[dim]{behind_tip}[/dim]")
    if sync.ahead > 0:
        diverge = (
            f"本地同时领先 {sync.ahead} 个提交，历史已分叉。"
            if chinese
            else f"Local is also ahead by {sync.ahead} commit(s); histories have diverged."
        )
        console.print(f"[yellow]{diverge}[/yellow]")

    dirty = is_worktree_dirty()
    if dirty:
        status_text = short_status()
        tip = (
            "工作区有未提交改动，拉取可能覆盖文件或产生冲突。建议先提交或 stash。"
            if chinese
            else "Working tree has uncommitted changes; pull may overwrite files or conflict. Commit or stash first."
        )
        console.print(f"[yellow]{tip}[/yellow]")
        if status_text:
            console.print(f"[dim]{status_text}[/dim]")
        if yes:
            err = (
                "已指定 --yes，为避免覆盖本地改动，已取消拉取。"
                if chinese
                else "Refusing to pull with --yes while the working tree is dirty."
            )
            err_console.print(f"[red]{err}[/red]")
            raise typer.Exit(code=1)
        proceed = (
            "仍要继续拉取？"
            if chinese
            else "Continue pull anyway?"
        )
        if not Confirm.ask(proceed, default=False):
            console.print("已取消拉取。" if chinese else "Pull aborted.")
            raise typer.Exit(code=0)

    use_rebase = bool(rebase)
    if rebase is None and sync.ahead > 0:
        if yes:
            use_rebase = False
            note = (
                "已指定 --yes：分叉时默认 merge 拉取。"
                if chinese
                else "--yes: using merge pull for diverged histories."
            )
            console.print(f"[dim]{note}[/dim]")
        else:
            strategy = Prompt.ask(
                "拉取方式" if chinese else "Pull strategy",
                choices=["merge", "rebase", "cancel"],
                default="merge",
            )
            if strategy == "cancel":
                console.print("已取消拉取。" if chinese else "Pull aborted.")
                raise typer.Exit(code=0)
            use_rebase = strategy == "rebase"
    elif rebase is None:
        ask = "确定从远程拉取（merge）？" if chinese else "Confirm merge-pull from remote?"
        if not yes and not Confirm.ask(ask, default=False):
            console.print("已取消拉取。" if chinese else "Pull aborted.")
            raise typer.Exit(code=0)
    else:
        mode = "rebase" if use_rebase else "merge"
        ask = (
            f"确定用 {mode} 从远程拉取？"
            if chinese
            else f"Confirm {mode}-pull from remote?"
        )
        if not yes and not Confirm.ask(ask, default=False):
            console.print("已取消拉取。" if chinese else "Pull aborted.")
            raise typer.Exit(code=0)

    pull_status = (
        ("正在变基拉取..." if use_rebase else "正在合并拉取...")
        if chinese
        else ("Pulling with rebase..." if use_rebase else "Pulling...")
    )
    with console.status(f"[bold]{pull_status}[/bold]"):
        try:
            git_pull(remote=remote, check=sync, rebase=use_rebase)
        except NothingToPull as exc:
            tip = (
                f"没有可拉取的内容：{exc}"
                if chinese
                else f"Nothing to pull: {exc}"
            )
            console.print(f"[yellow]{tip}[/yellow]")
            raise typer.Exit(code=0) from exc

    done = (
        f"已拉取 {sync.behind} 个提交：{sync.remote}/{sync.branch}"
        + ("（rebase）" if use_rebase else "")
        if chinese
        else f"Pulled {sync.behind} commit(s): {sync.remote}/{sync.branch}"
        + (" (rebase)" if use_rebase else "")
    )
    console.print(f"[green]{done}[/green]")


@app.command(
    "push",
    help=H(
        "Push the current branch to a configured remote (remote must already exist).",
        "将当前分支推送到已配置的远程仓库（需已存在 remote）。",
    ),
)
def push_cmd(
    remote: Optional[str] = typer.Option(
        None,
        "--remote",
        "-r",
        help=H(
            "Remote name (default: origin if present).",
            "远程名（默认优先 origin）。",
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation.", "跳过交互确认。"),
    ),
    set_upstream: bool = typer.Option(
        False,
        "--set-upstream",
        "-u",
        help=H(
            "Force git push -u even if upstream already exists.",
            "强制 git push -u（即使已有上游）。",
        ),
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
    """Push the current branch to a configured remote (remote must already exist)."""
    _start_trace(trace)
    try:
        _do_push(
            remote=remote,
            yes=yes,
            chinese=cn,
            set_upstream=True if set_upstream else None,
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
    "pull",
    help=H(
        "Pull updates from a configured remote. Checks for incoming commits and requires confirmation.",
        "从已配置的远程拉取更新。先检查是否有可拉取内容，并需确认。",
    ),
)
def pull_cmd(
    remote: Optional[str] = typer.Option(
        None,
        "--remote",
        "-r",
        help=H(
            "Remote name (default: origin if present).",
            "远程名（默认优先 origin）。",
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation.", "跳过交互确认。"),
    ),
    rebase: bool = typer.Option(
        False,
        "--rebase",
        help=H(
            "Pull with git pull --rebase instead of merge.",
            "使用 git pull --rebase（变基）而不是 merge。",
        ),
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
    """Pull from remote after verifying there is something to pull."""
    _start_trace(trace)
    try:
        _do_pull(remote=remote, yes=yes, chinese=cn, rebase=True if rebase else None)
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
