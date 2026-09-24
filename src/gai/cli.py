"""gai CLI entrypoint."""

from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from gai import __version__
from gai.config import CONFIG_FILE, load_settings, save_settings, settings_summary
from gai.git_ops import (
    GitError,
    NothingToPull,
    NothingToPush,
    add as git_add,
    check_sync,
    commit as git_commit,
    get_traced_commands,
    has_staged_changes,
    last_commit_subject,
    plan_push,
    pull as git_pull,
    push as git_push,
    set_tracing,
    short_status,
    unadd as git_unadd,
    uncommit as git_uncommit,
)
from gai.help_i18n import H
from gai.llm.client import LLMError
from gai.report import export_report, render_report, run_report
from gai.review import render_review, run_review

app = typer.Typer(
    name="gai",
    help=H(
        "Local Git commit & code review agent.",
        "本地 Git 提交与代码审查 Agent。",
    ),
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
err_console = Console(stderr=True)

_TRACE_OPT_HELP = H(
    "Print the underlying git command chain executed by this invocation.",
    "打印本次实际执行过的底层 git 命令链路。",
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gai {__version__}")
        raise typer.Exit()


def _start_trace(trace: bool) -> None:
    set_tracing(trace)


def _print_trace(*, trace: bool, chinese: bool = False) -> None:
    if not trace:
        return
    cmds = get_traced_commands()
    if not cmds:
        msg = (
            "本次未涉及 git 操作。"
            if chinese
            else "No git commands were executed in this invocation."
        )
        console.print(f"[dim]{msg}[/dim]")
        return
    title = "Git 命令链路：" if chinese else "Git command trace:"
    console.print()
    console.print(f"[bold]{title}[/bold]")
    for cmd in cmds:
        console.print(f"  [cyan]→[/cyan] {cmd}")


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
    _ = cn  # consumed for help language via argv; subcommands read their own --cn


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
    except (GitError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        _print_trace(trace=trace, chinese=cn)


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
    except (GitError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_trace(trace=trace, chinese=cn)


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
    except (GitError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_trace(trace=trace, chinese=cn)


@app.command(
    "review",
    help=H(
        "Review staged changes without committing.",
        "审查已暂存变更（不提交）。",
    ),
)
def review_cmd(
    as_json: bool = typer.Option(
        False,
        "--json",
        help=H(
            "Print structured JSON (for editors / VS Code integration).",
            "输出结构化 JSON（供编辑器 / 插件复用）。",
        ),
    ),
    message_only: bool = typer.Option(
        False,
        "--message-only",
        help=H(
            "Ask the model mainly for a commit message.",
            "主要让模型生成提交信息。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Output review findings and summary in Simplified Chinese.",
            "审查结论与摘要使用简体中文；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Review staged changes without committing."""
    _start_trace(trace)
    try:
        if not has_staged_changes():
            tip = (
                "没有已暂存变更。请先运行 `gai add` / `gai add .`。"
                if cn
                else "No staged changes. Run `gai add` / `gai add .` first."
            )
            err_console.print(f"[red]{tip}[/red]")
            raise typer.Exit(code=1)

        status_text = "正在调用大模型审查..." if cn else "Calling LLM for code review..."
        with console.status(f"[bold]{status_text}[/bold]"):
            result = run_review(
                message_only=message_only,
                review_only=not message_only,
                chinese=cn,
            )

        if as_json:
            console.print_json(data=result.to_dict())
        else:
            render_review(result, console, chinese=cn)
            if result.commit_message:
                console.print()
                label = "建议的提交信息：" if cn else "Suggested commit message:"
                console.print(f"[bold]{label}[/bold] {result.commit_message}")
    except (GitError, LLMError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    finally:
        _print_trace(trace=trace, chinese=cn)


@app.command(
    "commit",
    help=H(
        "Review staged changes, suggest a commit message, then confirm and commit.",
        "审查已暂存变更，建议提交信息，确认后提交。",
    ),
)
def commit_cmd(
    message: Optional[str] = typer.Option(
        None,
        "--message",
        "-m",
        help=H(
            "Use this commit message and skip AI message generation.",
            "使用指定提交信息，跳过 AI 生成 Message。",
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=H("Skip interactive confirmation.", "跳过交互确认。"),
    ),
    no_review: bool = typer.Option(
        False,
        "--no-review",
        help=H(
            "Skip code review; only generate (or use) the commit message.",
            "跳过代码审查，只生成（或使用）提交信息。",
        ),
    ),
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help=H(
            "Skip all AI calls. Requires --message.",
            "完全跳过 AI，必须同时提供 --message / -m。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Output review findings and summary in Simplified Chinese.",
            "审查与确认文案使用简体中文；与 -h 联用时显示中文帮助。",
        ),
    ),
    do_push: bool = typer.Option(
        False,
        "--push",
        help=H(
            "After a successful commit, push to the configured remote.",
            "提交成功后推送到已配置的远程仓库。",
        ),
    ),
    remote: Optional[str] = typer.Option(
        None,
        "--remote",
        "-r",
        help=H(
            "Remote name for --push (default: origin if present).",
            "配合 --push 指定远程名（默认优先 origin）。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Review staged changes, suggest a commit message, then confirm and commit."""
    _start_trace(trace)
    try:
        if not has_staged_changes():
            tip = (
                "没有已暂存变更。请先运行 `gai add` / `gai add .`。"
                if cn
                else "No staged changes. Run `gai add` / `gai add .` first."
            )
            err_console.print(f"[red]{tip}[/red]")
            status = short_status()
            if status:
                err_console.print("[dim]Working tree:[/dim]")
                err_console.print(status)
            raise typer.Exit(code=1)

        if no_ai:
            if not message:
                err_console.print("[red]--no-ai requires --message / -m.[/red]")
                raise typer.Exit(code=1)
            final_message = message.strip()
            _confirm_and_commit(
                final_message,
                yes=yes,
                chinese=cn,
                do_push=do_push,
                remote=remote,
            )
            return

        commit_message = (message or "").strip()
        result = None

        need_ai = (not commit_message) or (not no_review)
        if need_ai:
            status_text = "正在调用大模型..." if cn else "Calling LLM..."
            with console.status(f"[bold]{status_text}[/bold]"):
                result = run_review(
                    message_only=no_review and not commit_message,
                    review_only=not no_review and bool(commit_message),
                    chinese=cn,
                )

            if not no_review and result is not None:
                render_review(result, console, chinese=cn)
                console.print()

            if not commit_message and result is not None:
                if result.commit_message:
                    commit_message = result.commit_message
                elif not result.parsed_ok:
                    tip = (
                        "无法从模型输出中解析提交信息。"
                        if cn
                        else "Could not parse a commit message from the model."
                    )
                    err_console.print(f"[yellow]{tip}[/yellow]")

        if not commit_message:
            if yes:
                tip = (
                    "没有可用的提交信息，且已指定 --yes。"
                    if cn
                    else "No commit message available and --yes was set."
                )
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            prompt = "请输入提交信息" if cn else "Enter commit message"
            commit_message = Prompt.ask(prompt).strip()
            if not commit_message:
                tip = "提交信息为空，已取消。" if cn else "Empty commit message; aborted."
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            _confirm_and_commit(
                commit_message,
                yes=False,
                chinese=cn,
                do_push=do_push,
                remote=remote,
            )
            return

        label = "建议的提交信息：" if cn else "Suggested commit message:"
        console.print(f"[bold]{label}[/bold] {commit_message}")
        if yes:
            _do_commit(
                commit_message,
                chinese=cn,
                do_push=do_push,
                remote=remote,
                yes=yes,
            )
            return

        ask = "采纳该信息并提交？" if cn else "Adopt this message and commit?"
        if Confirm.ask(ask, default=True):
            _do_commit(
                commit_message,
                chinese=cn,
                do_push=do_push,
                remote=remote,
                yes=yes,
            )
            return

        edit_ask = (
            "编辑提交信息（留空则取消）"
            if cn
            else "Edit message (leave empty to abort)"
        )
        edited = Prompt.ask(edit_ask, default="").strip()
        if not edited:
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)
        _do_commit(
            edited,
            chinese=cn,
            do_push=do_push,
            remote=remote,
            yes=yes,
        )
    except (GitError, LLMError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_trace(trace=trace, chinese=cn)


def _confirm_and_commit(
    message: str,
    *,
    yes: bool,
    chinese: bool = False,
    do_push: bool = False,
    remote: str | None = None,
) -> None:
    label = "提交信息：" if chinese else "Commit message:"
    console.print(f"[bold]{label}[/bold] {message}")
    ask = "使用该信息提交？" if chinese else "Commit with this message?"
    if not yes and not Confirm.ask(ask, default=True):
        console.print("已取消。" if chinese else "Aborted.")
        raise typer.Exit(code=0)
    _do_commit(
        message,
        chinese=chinese,
        do_push=do_push,
        remote=remote,
        yes=yes,
    )


def _do_commit(
    message: str,
    *,
    chinese: bool = False,
    do_push: bool = False,
    remote: str | None = None,
    yes: bool = False,
) -> None:
    git_commit(message)
    label = "已提交：" if chinese else "Committed:"
    console.print(f"[green]{label}[/green] {message}")
    if do_push:
        _do_push(remote=remote, yes=yes, chinese=chinese)


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
    ask = "确定从远程拉取？" if chinese else "Confirm pull from remote?"
    if not yes and not Confirm.ask(ask, default=False):
        console.print("已取消拉取。" if chinese else "Pull aborted.")
        raise typer.Exit(code=0)

    pull_status = "正在拉取..." if chinese else "Pulling..."
    with console.status(f"[bold]{pull_status}[/bold]"):
        try:
            git_pull(remote=remote, check=sync)
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
        if chinese
        else f"Pulled {sync.behind} commit(s): {sync.remote}/{sync.branch}"
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
    except (GitError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_trace(trace=trace, chinese=cn)


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
        _do_pull(remote=remote, yes=yes, chinese=cn)
    except (GitError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_trace(trace=trace, chinese=cn)


@app.command(
    "report",
    help=H(
        "Summarize git commits into a paste-ready work report.",
        "根据提交记录生成可粘贴的工作总结。",
    ),
)
def report_cmd(
    since: str = typer.Option(
        "7d",
        "--since",
        "-s",
        help=H(
            "Start of range: 7d / 2w / 2026-09-01 / alltime (default: 7d).",
            "起始范围：7d / 2w / 2026-09-01 / alltime（默认 7d）。",
        ),
    ),
    until: Optional[str] = typer.Option(
        None,
        "--until",
        "-u",
        help=H(
            "End of range (YYYY-MM-DD or git-compatible date).",
            "结束范围（YYYY-MM-DD 或 git 可识别日期）。",
        ),
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help=H(
            "Filter by author. Use 'me' for current git user.",
            "按作者过滤；me 表示当前 git 用户。",
        ),
    ),
    max_count: int = typer.Option(
        100,
        "--max-count",
        "-n",
        help=H(
            "Max commits to include (alltime default becomes 500 if left at 100).",
            "最多纳入提交数（alltime 且仍为 100 时自动升为 500）。",
        ),
    ),
    no_stat: bool = typer.Option(
        False,
        "--no-stat",
        help=H(
            "Do not include git shortstat in the prompt.",
            "不把 shortstat 送给模型。",
        ),
    ),
    alltime: bool = typer.Option(
        False,
        "--alltime",
        help=H(
            "Summarize the full history (no --since filter). Same as --since alltime.",
            "总结全部历史（不加 since 过滤），等价于 --since alltime。",
        ),
    ),
    per: bool = typer.Option(
        False,
        "--per",
        help=H(
            "In team mode, also list concrete work per contributor.",
            "团队模式下按人列出具体完成内容。",
        ),
    ),
    out: Optional[str] = typer.Option(
        None,
        "--out",
        "-o",
        help=H(
            "Export Markdown. Bare -o → current dir + gai-report-YYYY-MM-DD.md; "
            "missing dirs are created; invalid format falls back to cwd.",
            "导出 Markdown。只写 -o → 当前目录 + gai-report-日期.md；"
            "缺目录自动创建；路径格式非法则回退当前目录。",
        ),
        flag_value=".",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=H("Print structured JSON.", "输出结构化 JSON。"),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Write the work report in Simplified Chinese.",
            "用简体中文写总结；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Summarize git commits into a paste-ready work report."""
    _start_trace(trace)
    try:
        # --alltime wins over a concrete --since (except alltime token itself).
        since_arg = since
        if alltime:
            concrete = since.strip().lower()
            if concrete not in {"7d", "alltime", "all-time", "all_time", "all"}:
                tip = (
                    f"--alltime 与 --since {since} 冲突，已按全部历史处理。"
                    if cn
                    else f"--alltime overrides --since {since}; using full history."
                )
                err_console.print(f"[yellow]{tip}[/yellow]")
            since_arg = "alltime"

        if per and author:
            tip = (
                "--per 在指定 --author 时无效（单人报告已是个人明细）。"
                if cn
                else "--per is ignored when --author is set (single-author report)."
            )
            err_console.print(f"[dim]{tip}[/dim]")

        status_text = "正在根据提交记录生成工作总结..." if cn else "Summarizing commits..."
        with console.status(f"[bold]{status_text}[/bold]"):
            result = run_report(
                since=since_arg,
                until=until,
                author=author,
                max_count=max_count,
                include_stat=not no_stat,
                chinese=cn,
                alltime=alltime or since_arg.strip().lower() in {
                    "alltime",
                    "all-time",
                    "all_time",
                    "all",
                },
                per_author=per,
            )

        if as_json:
            console.print_json(data=result.to_dict())
        else:
            render_report(result, console, chinese=cn)

        if out is not None:
            path, warning = export_report(result, out, chinese=cn)
            if warning:
                tip = f"提示：{warning}" if cn else f"Note: {warning}"
                # invalid format → yellow warning; created dir → dim tip
                style = "yellow" if "Invalid" in warning or "Falling back" in warning or "回退" in warning else "dim"
                err_console.print(f"[{style}]{tip}[/{style}]")
            saved = (
                f"已写入报告：{path}"
                if cn
                else f"Wrote report: {path}"
            )
            console.print(f"[green]{saved}[/green]")
    except (GitError, LLMError, RuntimeError, ValueError, OSError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        _print_trace(trace=trace, chinese=cn)


@app.command(
    "config",
    help=H(
        "View or update ~/.gai/config.toml.",
        "查看或更新 ~/.gai/config.toml。",
    ),
)
def config_cmd(
    show: bool = typer.Option(
        False,
        "--show",
        help=H(
            "Show current effective settings (secrets masked).",
            "显示当前生效配置（密钥已掩码）。",
        ),
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help=H("Set API key.", "设置 API Key。"),
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help=H(
            "Set OpenAI-compatible API base URL.",
            "设置 OpenAI 兼容 API Base URL。",
        ),
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help=H("Set model name.", "设置模型名。"),
    ),
    timeout: Optional[float] = typer.Option(
        None,
        "--timeout",
        help=H("HTTP timeout seconds.", "HTTP 超时秒数。"),
    ),
    max_diff_chars: Optional[int] = typer.Option(
        None,
        "--max-diff-chars",
        help=H(
            "Max staged-diff characters sent to the model.",
            "送入模型的文本最大字符数。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Show help in Simplified Chinese (use with -h/--help).",
            "与 -h/--help 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """View or update ~/.gai/config.toml."""
    _ = cn
    _start_trace(trace)
    try:
        updates = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
            "max_diff_chars": max_diff_chars,
        }
        if any(v is not None for v in updates.values()):
            path = save_settings(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_diff_chars=max_diff_chars,
            )
            console.print(f"[green]Saved[/green] {path}")

        if show or all(v is None for v in updates.values()):
            settings = load_settings()
            summary = settings_summary(settings)
            console.print(json.dumps(summary, indent=2, ensure_ascii=False))
            if not CONFIG_FILE.is_file() and not settings.api_key:
                console.print(
                    "\n[dim]Tip: set key via env GAI_API_KEY / OPENAI_API_KEY "
                    "or `gai config --api-key <key>`.[/dim]"
                )
    finally:
        _print_trace(trace=trace, chinese=cn)


if __name__ == "__main__":
    app()
    sys.exit(0)
