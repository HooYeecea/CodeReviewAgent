"""Review, commit, and guided devflow commands."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.prompt import Confirm, Prompt

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _print_llm_usage,
    _print_step_trace,
    _print_trace,
    _start_trace,
    app,
    console,
    err_console,
)
from gai.devflow import (
    normalize_path_input,
    stageable_paths_summary,
    suggest_bilingual_messages,
    suggest_stage_paths,
)
from gai.git_ops import (
    GitError,
    add as git_add,
    commit as git_commit,
    get_traced_commands,
    has_staged_changes,
    is_worktree_dirty,
    list_change_entries,
    short_status,
)
from gai.help_i18n import H
from gai.llm.client import LLMError
from gai.review import render_review, run_review

from gai.commands.sync import _do_push


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
    _start_trace(trace, action="review")
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
    except typer.Exit:
        raise
    except (GitError, LLMError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    finally:
        _print_footer(trace=trace, chinese=cn)


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
    except (GitError, LLMError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "devflow",
    help=H(
        "Guided flow: AI stage suggest → review → bilingual commit message → push.",
        "引导式流程：AI 暂存建议 → 审查 → 中英提交词自选 → 推送。",
    ),
)
def devflow_cmd(
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese for UI/review text. Commit still offers EN+CN choices.",
            "界面与审查文案用简体中文；提交词仍提供中英两种供选择。",
        ),
    ),
    remote: Optional[str] = typer.Option(
        None,
        "--remote",
        "-r",
        help=H(
            "Remote name for the final push step (default: origin if present).",
            "最后一步 push 的远程名（默认优先 origin）。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=H(
            "After each step, print the git commands that step executed.",
            "每一步结束后打印该步执行的 git 命令。",
        ),
    ),
) -> None:
    """Run add → review → commit → push with interactive decisions at each step."""
    _start_trace(trace, action="devflow")
    try:
        _run_devflow(chinese=cn, remote=remote, trace=trace)
    except typer.Exit:
        # Mid-flow cancel / early exit: show leftover git for the interrupted step.
        if get_traced_commands():
            _print_step_trace(
                trace=trace,
                chinese=cn,
                step="中断前" if cn else "before exit",
            )
        raise
    except (GitError, LLMError, RuntimeError) as exc:
        # Flush whatever this step accumulated before reporting the error.
        _print_step_trace(trace=trace, chinese=cn, step="error" if not cn else "出错时")
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        if get_traced_commands():
            _print_step_trace(
                trace=trace,
                chinese=cn,
                step="中断前" if cn else "before exit",
            )
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        # Per-step traces already flushed; only LLM summary (+ rare leftovers).
        console.print()
        _print_llm_usage(chinese=cn)
        if trace and get_traced_commands():
            _print_trace(trace=True, chinese=cn)


def _run_devflow(*, chinese: bool, remote: str | None, trace: bool = False) -> None:
    """Interactive add → review → commit → push pipeline."""
    step = (
        (lambda n, title: console.print(f"\n[bold cyan]━━ {n}. {title} ━━[/bold cyan]"))
        if chinese
        else (lambda n, title: console.print(f"\n[bold cyan]━━ {n}. {title} ━━[/bold cyan]"))
    )
    flush = lambda label: _print_step_trace(trace=trace, chinese=chinese, step=label)

    # ----- 1) ADD (AI suggest) -----
    step(1, "暂存 (add)" if chinese else "Stage (add)")
    if not is_worktree_dirty():
        tip = (
            "工作区干净，没有可暂存或可提交的变更。"
            if chinese
            else "Working tree is clean; nothing to stage or commit."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("add")
        raise typer.Exit(code=1)

    entries = list_change_entries()
    groups = stageable_paths_summary(entries)
    status = short_status()
    if status:
        console.print("[dim]" + status + "[/dim]")

    need_stage = bool(groups["untracked"] or groups["unstaged"])
    if need_stage:
        status_text = (
            "正在让 AI 建议暂存路径..."
            if chinese
            else "Asking AI which paths to stage..."
        )
        with console.status(f"[bold]{status_text}[/bold]"):
            suggestion = suggest_stage_paths(chinese=chinese)

        reason_label = "建议理由：" if chinese else "Why:"
        paths_label = "建议暂存：" if chinese else "Suggested paths:"
        console.print(f"[bold]{paths_label}[/bold] {' '.join(suggestion.paths)}")
        if suggestion.reason:
            console.print(f"[dim]{reason_label} {suggestion.reason}[/dim]")
        hint = (
            "快捷键：y=采纳 AI 建议 · .=全部暂存 · n=手输路径"
            if chinese
            else "Shortcuts: y=accept AI · .=stage all · n=edit paths"
        )
        console.print(f"[dim]{hint}[/dim]")

        choice = Prompt.ask(
            (
                "暂存方式 [y / . / n]"
                if chinese
                else "Stage how? [y / . / n]"
            ),
            default="y",
        ).strip().lower()
        if choice in {"y", "yes"}:
            targets = suggestion.paths
        elif choice in {".", "all", "*"}:
            targets = ["."]
        elif choice in {"n", "no", "e", "edit"}:
            manual = Prompt.ask(
                (
                    "请输入要暂存的路径（空格/逗号分隔；输入 . 表示全部）"
                    if chinese
                    else "Paths to stage (space/comma separated; . for all)"
                ),
                default=" ".join(suggestion.paths),
            ).strip()
            targets = normalize_path_input(manual) or suggestion.paths
        else:
            # Allow typing paths / "." directly at the first prompt.
            targets = normalize_path_input(choice) or suggestion.paths
        if not targets:
            tip = "未选择任何路径，已取消。" if chinese else "No paths selected; aborted."
            err_console.print(f"[red]{tip}[/red]")
            flush("add")
            raise typer.Exit(code=1)

        git_add(targets)
        msg = (
            f"已暂存：{' '.join(targets)}"
            if chinese
            else f"Staged: {' '.join(targets)}"
        )
        console.print(f"[green]{msg}[/green]")
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
    else:
        tip = (
            "没有未暂存变更，将使用当前暂存区继续。"
            if chinese
            else "Nothing new to stage; continuing with the current index."
        )
        console.print(f"[dim]{tip}[/dim]")

    if not has_staged_changes():
        tip = (
            "暂存区仍为空，无法继续审查/提交。"
            if chinese
            else "Nothing staged; cannot continue to review/commit."
        )
        err_console.print(f"[red]{tip}[/red]")
        flush("add")
        raise typer.Exit(code=1)

    flush("add")

    # ----- 2) REVIEW -----
    step(2, "代码审查 (review)" if chinese else "Code review")
    if chinese:
        review_cn = True
    else:
        lang = Prompt.ask(
            "Review language [cn/en]",
            default="en",
        ).strip().lower()
        review_cn = lang in {"cn", "zh", "chinese", "中文"}

    status_text = "正在调用大模型审查..." if chinese else "Calling LLM for code review..."
    with console.status(f"[bold]{status_text}[/bold]"):
        result = run_review(review_only=True, chinese=review_cn)
    render_review(result, console, chinese=review_cn)

    cont = Confirm.ask(
        "审查完成，继续选择提交信息？"
        if chinese
        else "Review done. Continue to commit message?",
        default=True,
    )
    flush("review")
    if not cont:
        console.print("已取消。" if chinese else "Aborted.")
        raise typer.Exit(code=0)

    # ----- 3) COMMIT (bilingual choice) -----
    step(3, "提交 (commit)" if chinese else "Commit")
    status_text = (
        "正在生成中英提交信息..."
        if chinese
        else "Generating English + Chinese commit messages..."
    )
    with console.status(f"[bold]{status_text}[/bold]"):
        messages = suggest_bilingual_messages()

    options: list[tuple[str, str]] = []
    if messages.message_en:
        options.append(("en", messages.message_en))
    if messages.message_cn:
        options.append(("cn", messages.message_cn))
    if not options:
        tip = (
            "未能解析中英提交信息，请手动输入。"
            if chinese
            else "Could not parse bilingual messages; enter one manually."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        commit_message = Prompt.ask(
            "请输入提交信息" if chinese else "Enter commit message"
        ).strip()
    else:
        console.print(
            "[bold]可选提交信息：[/bold]" if chinese else "[bold]Commit message choices:[/bold]"
        )
        for idx, (lang, text) in enumerate(options, start=1):
            tag = "英文" if lang == "en" else "中文"
            if not chinese:
                tag = "EN" if lang == "en" else "CN"
            console.print(f"  [cyan]{idx}[/cyan]) [{tag}] {text}")
        custom_n = len(options) + 1
        console.print(
            f"  [cyan]{custom_n}[/cyan]) "
            + ("手动输入" if chinese else "Type a custom message")
        )
        default_choice = "1"
        choice = Prompt.ask(
            "请选择" if chinese else "Choose",
            default=default_choice,
        ).strip()
        commit_message = ""
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(options):
                commit_message = options[n - 1][1]
            elif n == custom_n:
                commit_message = Prompt.ask(
                    "请输入提交信息" if chinese else "Enter commit message"
                ).strip()
        if not commit_message:
            # Also allow typing the message directly
            if choice and not choice.isdigit():
                commit_message = choice
            else:
                tip = "无效选择。" if chinese else "Invalid choice."
                err_console.print(f"[red]{tip}[/red]")
                flush("commit")
                raise typer.Exit(code=1)

    if not commit_message:
        tip = "提交信息为空，已取消。" if chinese else "Empty commit message; aborted."
        err_console.print(f"[red]{tip}[/red]")
        flush("commit")
        raise typer.Exit(code=1)

    label = "将使用的提交信息：" if chinese else "Commit message to use:"
    console.print(f"[bold]{label}[/bold] {commit_message}")
    if not Confirm.ask(
        "确认提交？" if chinese else "Confirm commit?",
        default=True,
    ):
        console.print("已取消提交。" if chinese else "Commit aborted.")
        flush("commit")
        raise typer.Exit(code=0)

    git_commit(commit_message)
    console.print(
        ("[green]已提交：[/green] " if chinese else "[green]Committed:[/green] ")
        + commit_message
    )
    flush("commit")

    # ----- 4) PUSH -----
    step(4, "推送 (push)" if chinese else "Push")
    if not Confirm.ask(
        "确认推送到远程？" if chinese else "Push to remote?",
        default=True,
    ):
        console.print(
            "已跳过推送。提交已保留在本地。"
            if chinese
            else "Push skipped. Commit kept locally."
        )
        flush("push")
        raise typer.Exit(code=0)

    _do_push(remote=remote, yes=True, chinese=chinese)
    flush("push")


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

