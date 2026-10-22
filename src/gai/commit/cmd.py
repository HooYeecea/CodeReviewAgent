"""gai commit command."""

from __future__ import annotations

from typing import Optional

import typer
from rich.prompt import Confirm, Prompt

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
    err_console,
)
from gai.common.git import GitError, commit as git_commit, has_staged_changes, short_status
from gai.common.i18n import H
from gai.common.llm.client import LLMError
from gai.review import DiffTooLargeError, render_review, run_review, staged_diff_size
from gai.review.helpers import (
    _SUGGEST_SPLIT_HELP,
    _maybe_suggest_optional_splitflow,
    _offer_splitflow_instead,
)
from gai.sync.push_pull import _do_push

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
    suggest_split: bool = typer.Option(
        False,
        "--suggest-split",
        help=_SUGGEST_SPLIT_HELP,
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Review staged changes, suggest a commit message, then confirm and commit."""
    _start_trace(trace, action="commit")
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
            chars, limit, exceeds = staged_diff_size()
            if exceeds:
                _offer_splitflow_instead(
                    chinese=cn,
                    remote=remote,
                    trace=trace,
                    interactive=not yes,
                    chars=chars,
                    limit=limit,
                )
            elif suggest_split:
                _maybe_suggest_optional_splitflow(
                    chinese=cn,
                    remote=remote,
                    trace=trace,
                    interactive=not yes,
                )
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
    except typer.Exit:
        raise
    except DiffTooLargeError as exc:
        _offer_splitflow_instead(
            chinese=cn,
            remote=remote,
            trace=trace,
            interactive=not yes,
            chars=exc.chars,
            limit=exc.limit,
        )
    except (GitError, LLMError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


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
