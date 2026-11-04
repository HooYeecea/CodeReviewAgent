"""gai review command."""

from __future__ import annotations

from contextlib import redirect_stdout
import sys

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
from gai.review.archive import collect_reviews, save_review as archive_review
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
        "Review staged or committed branch changes without committing.",
        "审查暂存或分支改动（不提交）。",
    ),
)
@collect_reviews("review")
def review_cmd(
    fail_on: str | None = typer.Option(None, "--fail-on", help=H("Block at critical, warning, info; none disables.", "阻断级别：critical、warning、info；none 关闭。")),
    require_complete: bool | None = typer.Option(None, "--require-complete/--allow-incomplete", help=H("Require complete coverage.", "要求完整审查覆盖。")),
    base: str | None = typer.Option(None, "--base", help=H("Review committed branch changes since the merge base.", "审查分支相对共同祖先的已提交改动。")),
    chunked: bool = typer.Option(False, "--chunked", help=H("Review large diffs in chunks without splitting commits.", "分段审查大改动，不拆分提交。")),
    save_review: bool = typer.Option(False, "--save-review", help=H(
        "Save actual reviews as Markdown and JSON in .gai/reviews/.",
        "将实际代码审查结果保存为 Markdown 和 JSON，位于 .gai/reviews/。")),
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
        if (base or chunked) and message_only:
            raise RuntimeError("--base / --chunked cannot be combined with --message-only")
        if not base and not has_staged_changes():
            tip = (
                "没有已暂存变更。请先运行 `gai add` / `gai add .`。"
                if cn
                else "No staged changes. Run `gai add` / `gai add .` first."
            )
            err_console.print(f"[red]{tip}[/red]")
            raise typer.Exit(code=1)

        from gai.review.branch import load_branch_diff_info
        diff_info = load_branch_diff_info(base) if base else load_staged_diff_info()
        if diff_info.exceeds and not chunked:
            if base:
                raise RuntimeError("分支改动过大，请加 --chunked / Branch diff too large; use --chunked")
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
        elif suggest_split and not as_json and not base and not chunked:
            _maybe_suggest_optional_splitflow(
                chinese=cn, trace=trace, interactive=True
            )

        status_text = "正在调用大模型审查..." if cn else "Calling LLM for code review..."
        with (err_console if as_json else console).status(f"[bold]{status_text}[/bold]"):
            result = run_review(
                message_only=message_only,
                review_only=not message_only,
                chinese=cn,
                diff_info=diff_info,
                **({"chunked": True} if chunked else {}),
            )

        if not message_only:
            archive_review(result, diff_info.snapshot, chinese=cn)
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
        if not message_only:
            from gai.review.policy import enforce
            enforce(result)
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
        if as_json:
            with redirect_stdout(sys.stderr):
                _print_footer(trace=trace, chinese=cn)
        else:
            _print_footer(trace=trace, chinese=cn)


