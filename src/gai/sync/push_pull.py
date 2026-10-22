"""Push and pull commands."""

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
    NothingToPull,
    NothingToPush,
    check_sync,
    is_worktree_dirty,
    plan_push,
    pull as git_pull,
    push as git_push,
    short_status,
)
from gai.common.i18n import H

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


