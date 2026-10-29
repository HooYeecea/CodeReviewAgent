"""gai review command."""

from __future__ import annotations

import typer

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
    err_console,
)
from gai.common.git import GitError, has_staged_changes
from gai.common.i18n import H
from gai.common.llm.client import LLMError
from gai.review import (
    DiffTooLargeError,
    load_staged_diff_info,
    render_review,
    run_review,
)
from gai.review.helpers import (
    _SUGGEST_SPLIT_HELP,
    _maybe_suggest_optional_splitflow,
    _offer_splitflow_instead,
    _print_diff_too_large,
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

        diff_info = load_staged_diff_info()
        if diff_info.exceeds:
            if as_json:
                _print_diff_too_large(
                    chars=diff_info.chars, limit=diff_info.limit, chinese=cn
                )
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
                chars=diff_info.chars,
                limit=diff_info.limit,
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
                diff_info=diff_info,
            )

        if as_json:
            console.print_json(data=result.to_dict())
        else:
            render_review(result, console, chinese=cn)
            if result.commit_message:
                console.print()
                label = "建议的提交信息：" if cn else "Suggested commit message:"
                console.print(f"[bold]{label}[/bold] {result.commit_message}")
        if not result.parsed_ok:
            raise typer.Exit(code=1)
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


