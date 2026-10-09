"""Shared Typer app, consoles, and per-command helpers for gai CLI."""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Confirm
import typer

from gai import __version__
from gai.errors import format_cli_error
from gai.git_ops import (
    clear_trace,
    get_traced_commands,
    is_worktree_dirty,
    set_tracing,
    short_status,
)
from gai.help_i18n import H
from gai.llm.usage import clear_llm_usage, get_llm_calls, set_llm_action, usage_totals
from gai.completion_cmd import completion_app

app = typer.Typer(
    name="gai",
    help=H(
        "Local Git commit & code review agent.",
        "本地 Git 提交与代码审查 Agent。",
    ),
    no_args_is_help=True,
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(completion_app, name="completion")

console = Console()
err_console = Console(stderr=True)

TRACE_OPT_HELP = H(
    "Print the underlying git command chain executed by this invocation.",
    "打印本次实际执行过的底层 git 命令链路。",
)
# Backward-compatible alias used throughout command modules.
_TRACE_OPT_HELP = TRACE_OPT_HELP

_LLM_USAGE_PRINTED = False


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gai {__version__}")
        raise typer.Exit()


def _start_trace(trace: bool, *, action: str = "") -> None:
    set_tracing(trace)
    clear_llm_usage()
    if action:
        set_llm_action(action)
    global _LLM_USAGE_PRINTED
    _LLM_USAGE_PRINTED = False


def _print_llm_usage(*, chinese: bool = False, once: bool = True) -> None:
    """Report whether this invocation called the LLM (yellow). Skip if already printed."""
    global _LLM_USAGE_PRINTED
    if once and _LLM_USAGE_PRINTED:
        return

    calls = get_llm_calls()
    if not calls:
        msg = (
            "本次命令未涉及调用大模型。"
            if chinese
            else "This command did not call the LLM."
        )
        console.print(f"[yellow]{msg}[/yellow]")
        _LLM_USAGE_PRINTED = True
        return

    models: list[str] = []
    for c in calls:
        if c.model and c.model not in models:
            models.append(c.model)
    model_text = "、".join(models) if chinese else ", ".join(models)
    prompt, completion, total = usage_totals(calls)
    n = len(calls)

    if chinese:
        head = (
            f"本次命令已调用大模型（{n} 次）：模型 {model_text}"
            if n > 1
            else f"本次命令已调用大模型：模型 {model_text}"
        )
        if total is not None:
            detail = f"，消耗 token {total}"
            parts = []
            if prompt is not None:
                parts.append(f"输入 {prompt}")
            if completion is not None:
                parts.append(f"输出 {completion}")
            if parts:
                detail += f"（{' + '.join(parts)}）"
            head += detail
        elif prompt is not None or completion is not None:
            bits = []
            if prompt is not None:
                bits.append(f"输入 {prompt}")
            if completion is not None:
                bits.append(f"输出 {completion}")
            head += f"（{' + '.join(bits)}；未返回合计 token）"
        else:
            head += "（接口未返回 token 用量）"
        console.print(f"[yellow]{head}。[/yellow]")
    else:
        head = (
            f"This command called the LLM ({n} time(s)): model {model_text}"
            if n > 1
            else f"This command called the LLM: model {model_text}"
        )
        if total is not None:
            detail = f", {total} tokens"
            parts = []
            if prompt is not None:
                parts.append(f"prompt {prompt}")
            if completion is not None:
                parts.append(f"completion {completion}")
            if parts:
                detail += f" ({' + '.join(parts)})"
            head += detail
        elif prompt is not None or completion is not None:
            bits = []
            if prompt is not None:
                bits.append(f"prompt {prompt}")
            if completion is not None:
                bits.append(f"completion {completion}")
            head += f" ({' + '.join(bits)}; no total tokens returned)"
        else:
            head += " (provider did not return token usage)"
        console.print(f"[yellow]{head}.[/yellow]")

    _LLM_USAGE_PRINTED = True


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


def _print_step_trace(*, trace: bool, chinese: bool, step: str) -> None:
    """Print git commands for one devflow step, then clear the buffer."""
    if not trace:
        return
    cmds = get_traced_commands()
    title = (
        f"本步 Git 链路（{step}）："
        if chinese
        else f"Git commands this step ({step}):"
    )
    console.print()
    console.print(f"[bold]{title}[/bold]")
    if not cmds:
        empty = "（本步未执行 git）" if chinese else "(no git in this step)"
        console.print(f"[dim]  {empty}[/dim]")
    else:
        for cmd in cmds:
            console.print(f"  [cyan]→[/cyan] {cmd}")
    clear_trace()


def _print_footer(*, trace: bool, chinese: bool = False) -> None:
    console.print()
    _print_llm_usage(chinese=chinese)
    _print_trace(trace=trace, chinese=chinese)


def _print_error(
    exc: BaseException,
    *,
    chinese: bool = False,
    trace: bool = False,
) -> None:
    """Print a friendly error; with --trace also show raw detail when available."""
    label = "错误：" if chinese else "Error:"
    msg = format_cli_error(exc, chinese=chinese)
    err_console.print(f"[red]{label}[/red] {msg}")
    detail = getattr(exc, "detail", None)
    if trace and detail:
        tip = "原始详情：" if chinese else "Raw detail:"
        err_console.print(f"[dim]{tip} {detail}[/dim]")


def _confirm_dirty_continue(*, chinese: bool, yes: bool, action: str) -> None:
    """Warn on dirty worktree; refuse with --yes; otherwise ask to continue."""
    if not is_worktree_dirty():
        return
    status_text = short_status()
    tip = (
        f"工作区有未提交改动，{action} 可能覆盖文件或产生冲突。建议先提交或 stash。"
        if chinese
        else f"Working tree has uncommitted changes; {action} may overwrite files or conflict. Commit or stash first."
    )
    console.print(f"[yellow]{tip}[/yellow]")
    if status_text:
        console.print(f"[dim]{status_text}[/dim]")
    if yes:
        err = (
            f"已指定 --yes，为避免覆盖本地改动，已取消{action}。"
            if chinese
            else f"Refusing to {action} with --yes while the working tree is dirty."
        )
        err_console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=1)
    proceed = f"仍要继续{action}？" if chinese else f"Continue {action} anyway?"
    if not Confirm.ask(proceed, default=False):
        console.print(("已取消。" if chinese else "Aborted."))
        raise typer.Exit(code=0)
