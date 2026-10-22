"""Guided flow commands: splitflow and devflow."""

from __future__ import annotations

from typing import Optional

import typer

from gai.cli_common import (
    _print_error,
    _print_llm_usage,
    _print_step_trace,
    _print_trace,
    _start_trace,
    app,
    console,
)
from gai.git_ops import GitError, get_traced_commands
from gai.help_i18n import H
from gai.llm.client import LLMError
from gai.review import DiffTooLargeError

from gai.commands.flow_lib import (  # noqa: F401
    _run_devflow,
    _run_splitflow,
    parse_batch_message_lang_spec,
)
from gai.commands.ship import _SUGGEST_SPLIT_HELP, _offer_splitflow_instead

@app.command(
    "splitflow",
    help=H(
        "Split a large dirty tree into coherent commits, then review+commit each batch.",
        "把大量未提交改动按主题拆成多次审查/提交（合理 commit 边界）。",
    ),
)
def splitflow_cmd(
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
            "全部批次完成后 push 的远程名（默认优先 origin）。",
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
    """Plan commit batches with AI, then run review→commit for each batch."""
    _start_trace(trace, action="splitflow")
    try:
        _run_splitflow(chinese=cn, remote=remote, trace=trace)
    except typer.Exit:
        if get_traced_commands():
            _print_step_trace(
                trace=trace,
                chinese=cn,
                step="中断前" if cn else "before exit",
            )
        raise
    except (GitError, LLMError, RuntimeError) as exc:
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
        console.print()
        _print_llm_usage(chinese=cn)
        if trace and get_traced_commands():
            _print_trace(trace=True, chinese=cn)


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
    suggest_split: bool = typer.Option(
        False,
        "--suggest-split",
        help=_SUGGEST_SPLIT_HELP,
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
        _run_devflow(
            chinese=cn, remote=remote, trace=trace, suggest_split=suggest_split
        )
    except typer.Exit:
        # Mid-flow cancel / early exit: show leftover git for the interrupted step.
        if get_traced_commands():
            _print_step_trace(
                trace=trace,
                chinese=cn,
                step="中断前" if cn else "before exit",
            )
        raise
    except DiffTooLargeError as exc:
        _print_step_trace(trace=trace, chinese=cn, step="error" if not cn else "出错时")
        _offer_splitflow_instead(
            chinese=cn,
            remote=remote,
            trace=trace,
            interactive=True,
            chars=exc.chars,
            limit=exc.limit,
        )
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


