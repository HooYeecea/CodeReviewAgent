"""Review and commit commands (splitflow/devflow live in flow.py)."""

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
from gai.devflow import CommitBatchPlan, list_staged_paths, suggest_commit_batches
from gai.git_ops import GitError, commit as git_commit, has_staged_changes, short_status
from gai.help_i18n import H
from gai.llm.client import LLMError
from gai.review import DiffTooLargeError, render_review, run_review, staged_diff_size

from gai.commands.sync import _do_push

_SUGGEST_SPLIT_HELP = H(
    "Ask AI whether to split into multiple commits even when the diff fits the limit.",
    "即使 Diff 未超限，也询问 AI 是否拆成多次提交（会额外调用一次模型）。",
)


def _print_diff_too_large(*, chars: int, limit: int, chinese: bool) -> None:
    if chinese:
        console.print(
            f"[yellow]Diff 过大（约 {chars} 字符，上限 {limit}），"
            "整包审查会被截断，审查可能不完整。[/yellow]"
        )
        console.print(
            "[dim]建议改用 `gai splitflow`：按主题拆成多次完整审查/提交。[/dim]"
        )
    else:
        console.print(
            f"[yellow]Diff is too large (~{chars} chars, limit {limit}); "
            "a single review would be truncated and incomplete.[/yellow]"
        )
        console.print(
            "[dim]Prefer `gai splitflow`: split into coherent review/commit batches.[/dim]"
        )


def _offer_splitflow_instead(
    *,
    chinese: bool,
    remote: str | None = None,
    trace: bool = False,
    interactive: bool = True,
    plan: CommitBatchPlan | None = None,
    required: bool = True,
    chars: int | None = None,
    limit: int | None = None,
) -> None:
    """Ask to switch to splitflow.

    When ``required`` is true (diff would truncate), declining aborts.
    When false (optional AI split tip), declining returns and the caller continues.
    Switching always ends with ``typer.Exit(0)``.
    """
    if required:
        if chars is None or limit is None:
            chars, limit, exceeds = staged_diff_size()
        else:
            exceeds = chars > limit
        if not exceeds and plan is None:
            return
        if exceeds:
            _print_diff_too_large(chars=chars, limit=limit, chinese=chinese)
    if not interactive:
        tip = (
            "请改跑：gai splitflow --cn"
            if chinese
            else "Run instead: gai splitflow"
        )
        err_console.print(f"[red]{tip}[/red]")
        raise typer.Exit(code=1)
    ask = (
        "是否切换到 splitflow？"
        if chinese
        else "Switch to splitflow now?"
    )
    if Confirm.ask(ask, default=required):
        console.print(
            "[green]已切换到 splitflow。[/green]"
            if chinese
            else "[green]Switching to splitflow.[/green]"
        )
        from gai.commands.flow import _run_splitflow

        _run_splitflow(chinese=chinese, remote=remote, trace=trace, plan=plan)
        raise typer.Exit(code=0)
    if required:
        console.print(
            "已取消（未对截断 Diff 继续审查）。"
            if chinese
            else "Aborted (will not review a truncated diff)."
        )
        raise typer.Exit(code=1)
    console.print(
        "[dim]继续整包审查/提交。[/dim]"
        if chinese
        else "[dim]Continuing with a single review/commit.[/dim]"
    )


def _maybe_suggest_optional_splitflow(
    *,
    chinese: bool,
    remote: str | None = None,
    trace: bool = False,
    interactive: bool = True,
) -> None:
    """If AI finds multiple coherent batches (even when diff fits), offer splitflow.

    Callers must gate this behind ``--suggest-split`` (opt-in) to avoid an extra
    LLM call on every review/commit.
    """
    _, _, exceeds = staged_diff_size()
    if exceeds:
        return  # hard path handled by caller
    staged_paths = list_staged_paths()
    if len(staged_paths) < 2:
        return
    if not interactive:
        return

    status_text = (
        "正在分析是否适合拆成多次提交..."
        if chinese
        else "Checking whether changes should be split into multiple commits..."
    )
    with console.status(f"[bold]{status_text}[/bold]"):
        plan = suggest_commit_batches(chinese=chinese, only_staged=True)

    # Only trust a real model plan with 2+ batches (ignore directory fallback noise).
    if not plan.parsed_ok or len(plan.batches) < 2:
        return

    console.print(
        (
            f"[yellow]AI 建议拆成 {len(plan.batches)} 个更清晰的提交"
            "（当前 Diff 虽未超限，但主题可分开）。[/yellow]"
            if chinese
            else (
                f"[yellow]AI suggests {len(plan.batches)} clearer commits "
                "(diff fits the limit, but themes can be separated).[/yellow]"
            )
        )
    )
    from gai.commands.flow import _print_batch_plan

    _print_batch_plan(plan.batches, summary=plan.summary, chinese=chinese)
    _offer_splitflow_instead(
        chinese=chinese,
        remote=remote,
        trace=trace,
        interactive=True,
        plan=plan,
        required=False,
    )


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

        chars, limit, exceeds = staged_diff_size()
        if exceeds:
            if as_json:
                _print_diff_too_large(chars=chars, limit=limit, chinese=cn)
                tip = (
                    "请改跑：gai splitflow --cn"
                    if cn
                    else "Run instead: gai splitflow"
                )
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            _offer_splitflow_instead(
                chinese=cn,
                trace=trace,
                interactive=True,
                chars=chars,
                limit=limit,
            )
        elif suggest_split and not as_json:
            _maybe_suggest_optional_splitflow(
                chinese=cn, trace=trace, interactive=True
            )

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
    except DiffTooLargeError as exc:
        if as_json:
            _print_diff_too_large(chars=exc.chars, limit=exc.limit, chinese=cn)
            tip = (
                "请改跑：gai splitflow --cn"
                if cn
                else "Run instead: gai splitflow"
            )
            err_console.print(f"[red]{tip}[/red]")
            raise typer.Exit(code=1)
        _offer_splitflow_instead(
            chinese=cn,
            trace=trace,
            interactive=True,
            chars=exc.chars,
            limit=exc.limit,
        )
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
