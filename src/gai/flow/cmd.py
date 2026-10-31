"""Guided flow commands: splitflow and devflow."""

from __future__ import annotations

from typing import Optional

import typer
from rich.prompt import Confirm

from gai.cli_common import (
    _print_error,
    _print_llm_usage,
    _print_step_trace,
    _print_trace,
    _start_trace,
    app,
    console,
)
from gai.common.git import GitError, get_traced_commands
from gai.common.i18n import H
from gai.common.llm.client import LLMError
from gai.review import DiffTooLargeError

from gai.flow.lib import (  # noqa: F401
    _run_devflow,
    _run_splitflow,
    parse_batch_message_lang_spec,
)
from gai.review.helpers import _SUGGEST_SPLIT_HELP, _offer_splitflow_instead

@app.command(
    "splitflow",
    help=H(
        "Split a large dirty tree into coherent commits, then review+commit each batch.",
        "把大量未提交改动按主题拆成多次审查/提交（合理 commit 边界）。",
    ),
)
def splitflow_cmd(
    resume: bool = typer.Option(False, "--resume", help=H("Resume the saved flow.", "从已保存的检查点继续。")),
    interactive: bool = typer.Option(False, "--interactive", help=H("Restore interactive confirmations.", "恢复人工确认，保留流程进度。")),
    no_push: bool = typer.Option(False, "--no-push", help=H("Complete locally without pushing.", "完成本地提交后结束，不推送。")),
    review_current: bool = typer.Option(False, "--review-current", help=H("With --resume, restage and review the edited current batch.", "配合 --resume，重新暂存并审查修改后的当前批次。")),
    replan: bool = typer.Option(False, "--replan", help=H("With --resume, preserve commits and replan remaining changes.", "配合 --resume，保留已完成提交并重规划剩余改动。")),
    yes: bool = typer.Option(
        False, "--yes", "-y", help=H(
            "Auto-confirm through push; only ask for commit message language. Saved on resume.",
            "自动确认直到推送，只询问提交词语言；断点恢复沿用此设置。",
        ),
    ),
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
        _run_splitflow(chinese=cn, remote=remote, trace=trace, resume=resume, yes=yes,
                      interactive=interactive, no_push=no_push, review_current=review_current, replan=replan)
    except typer.Exit:
        if get_traced_commands():
            _print_step_trace(
                trace=trace,
                chinese=cn,
                step="中断前" if cn else "before exit",
            )
        raise
    except (GitError, LLMError, RuntimeError, OSError) as exc:
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
    resume: bool = typer.Option(False, "--resume", help=H("Resume the saved flow.", "从已保存的检查点继续。")),
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
            chinese=cn, remote=remote, trace=trace, suggest_split=suggest_split, resume=resume
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
    except (GitError, LLMError, RuntimeError, OSError) as exc:
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


flow_app = typer.Typer(help=H("Inspect or discard saved flows.", "查看或放弃已保存的流程。"))
app.add_typer(flow_app, name="flow")


@flow_app.command("status")
def flow_status(cn: bool = typer.Option(False, "--cn"),
                check: bool = typer.Option(False, "--check", help=H("Preview recovery without staging, committing or pushing.", "预检恢复条件，不暂存、提交或推送。"))) -> None:
    from gai.flow.session import read_state, preview_recovery
    _start_trace(False, action="flow-status")
    try:
        data = read_state(allow_backup=check)
        if data is None:
            console.print("没有流程记录。" if cn else "No saved flow.")
            return
        if data.get("_backup_pending"):
            console.print("当前检查点损坏，正在预检上一份记录 / Checking backup checkpoint")
        batches = data.get("completed_batches", []) + data["batches"]
        done = sum(b["status"] == "committed" for b in batches)
        if data["kind"] == "splitflow":
            console.print(f"自动确认 / Auto-confirm: {'on' if data.get('auto_confirm') else 'off'}")
        console.print(f"{data['kind']}  {data['id']}\n"
                      f"阶段 / Phase: {data['phase']}\n"
                      f"已提交 / Committed: {done}/{len(batches)}\n"
                      f"更新 / Updated: {data.get('updated_at', 'unknown')}\n"
                      f"最近成功步骤 / Last success: {data.get('last_success', 'none')}\n"
                      f"版本 / Revision: {data.get('revision', 'legacy')}", markup=False)
        if data.get("last_error"):
            error = data["last_error"]
            console.print(f"最近失败 / Last failure: {error['kind']} "
                          f"({error.get('step', error['phase'])}, batch {error['batch'] + 1}, {error['at']})", markup=False)
        if data.get("completion"):
            console.print(f"完成方式 / Completion: {data['completion']}", markup=False)
        if data.get("no_push"):
            console.print("仅本地提交 / Local commits only")
        for batch in batches:
            console.print(f"{batch['label']}: {batch['batch']['title']} — {batch['status']} "
                          f"{batch.get('commit', '')}", markup=False)
        if data.get("pending"):
            console.print(f"待核实操作 / Pending operation: {data['pending']['operation']}", markup=False)
        if data["phase"] not in {"done", "aborted"}:
            console.print(f"gai {data['kind']} --resume", markup=False)
            if check:
                preview_recovery()
    except (GitError, RuntimeError, OSError) as exc:
        _print_error(exc, chinese=cn, trace=False)
        raise typer.Exit(1) from exc


@flow_app.command("abort")
def flow_abort(cn: bool = typer.Option(False, "--cn")) -> None:
    from gai.flow.session import write_checkpoint, flow_lock, read_state, session_dir
    _start_trace(False, action="flow-abort")
    try:
        directory = session_dir()
        with flow_lock(directory):
            try:
                data = read_state(directory)
            except RuntimeError:
                if Confirm.ask(
                    "检查点损坏，归档并放弃这份记录？文件、暂存区和提交均保留。" if cn
                    else "Archive the unreadable checkpoint? Git state will be kept.", default=False,
                ):
                    import uuid
                    for name in ("current.json", "previous.json"):
                        path = directory / name
                        if path.exists():
                            path.replace(directory / f"corrupt-{uuid.uuid4().hex}.json")
                    console.print("已归档损坏的记录。" if cn else "Unreadable checkpoint archived.")
                return
            if data is None or data["phase"] in {"done", "aborted"}:
                console.print("没有未完成流程。" if cn else "No unfinished flow.")
                return
            if not Confirm.ask(
                "放弃流程记录？文件、暂存区和已有提交均保留。" if cn
                else "Discard flow? Files, index and existing commits will be kept.", default=False,
            ):
                return
            data["phase"] = "aborted"
            write_checkpoint(directory, data)
            console.print("已放弃流程，代码与提交保持原样。" if cn else "Flow discarded; Git state unchanged.")
    except (GitError, RuntimeError, OSError) as exc:
        _print_error(exc, chinese=cn, trace=False)
        raise typer.Exit(1) from exc


