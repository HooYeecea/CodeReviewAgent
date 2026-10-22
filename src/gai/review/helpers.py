"""Shared review/commit helpers (diff-too-large + optional splitflow offer)."""

from __future__ import annotations

import typer
from rich.prompt import Confirm

from gai.cli_common import console, err_console
from gai.flow.devflow import CommitBatchPlan, list_staged_paths, suggest_commit_batches
from gai.common.git import has_staged_changes
from gai.common.i18n import H
from gai.review import staged_diff_size

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
        from gai.flow.lib import _run_splitflow

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
    from gai.flow.lib import _print_batch_plan

    _print_batch_plan(plan.batches, summary=plan.summary, chinese=chinese)
    _offer_splitflow_instead(
        chinese=chinese,
        remote=remote,
        trace=trace,
        interactive=True,
        plan=plan,
        required=False,
    )


