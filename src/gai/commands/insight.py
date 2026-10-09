"""Report, usage, history, and guide commands."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

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
from gai.command_history import (
    command_log_path,
    format_command_table,
    load_command_records,
)
from gai.errors import PeriodError
from gai.git_ops import GitError
from gai.help_i18n import H
from gai.llm.client import LLMError
from gai.history_report import history_report_path, write_history_report
from gai.guide import write_guide_html
from gai.llm.history import format_usage_table, load_usage_records, usage_log_path
from gai.llm.usage_report import path_to_file_url, usage_report_path, write_usage_report
from gai.local_serve import open_path, serve_gai_page
from gai.log_store import (
    ensure_global_logs_merged,
    global_command_log_path,
    global_history_report_path,
    global_usage_log_path,
    global_usage_report_path,
)
from gai.report import export_report, render_report, run_report


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
    _start_trace(trace, action="report")
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
    except typer.Exit:
        raise
    except (GitError, LLMError, PeriodError, RuntimeError, ValueError, OSError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    finally:
        _print_footer(trace=trace, chinese=cn)


def _parse_usage_since(value: str | None) -> datetime | None:
    """Parse --since for usage history: 7d / 2w / 1m / 1y / YYYY-MM-DD."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    lower = text.lower()
    if lower in {"alltime", "all-time", "all_time", "all"}:
        return None
    rel = re.fullmatch(r"(\d+)\s*([dwmy])", lower)
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2)
        now = datetime.now(timezone.utc).astimezone()
        if unit == "d":
            return now - timedelta(days=amount)
        if unit == "w":
            return now - timedelta(weeks=amount)
        if unit == "m":
            return now - timedelta(days=30 * amount)
        return now - timedelta(days=365 * amount)
    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise PeriodError("invalid_since", value=value) from exc
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).astimezone()


@app.command(
    "usage",
    help=H(
        "Show local LLM token usage history recorded by gai.",
        "查看 gai 本地记录的大模型 token 用量历史。",
    ),
)
def usage_cmd(
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help=H(
            "Max records to show (newest first after filters; default 20).",
            "最多显示条数（过滤后取最新；默认 20）。",
        ),
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        "-s",
        help=H(
            "Only records after this time: 7d / 2w / 1m / 1y / YYYY-MM-DD / alltime.",
            "只看该时间之后：7d / 2w / 1m / 1y / YYYY-MM-DD / alltime。",
        ),
    ),
    action: Optional[str] = typer.Option(
        None,
        "--action",
        "-a",
        help=H(
            "Filter by action: review / commit / report.",
            "按动作过滤：review / commit / report。",
        ),
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help=H(
            "Filter by provider id (e.g. deepseek, openai).",
            "按厂商 id 过滤（如 deepseek、openai）。",
        ),
    ),
    user: Optional[str] = typer.Option(
        None,
        "--user",
        "-u",
        help=H(
            "Filter by git user name or email substring.",
            "按 git 用户名或邮箱子串过滤。",
        ),
    ),
    group: Optional[str] = typer.Option(
        None,
        "--group",
        "-g",
        help=H(
            "Also summarize by: action / provider / model / user.",
            "额外按 action / provider / model / user 汇总。",
        ),
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=H("Print records as JSON.", "以 JSON 输出记录。"),
    ),
    report: bool = typer.Option(
        False,
        "--report",
        help=H(
            "Sync HTML dashboard under ~/.gai from the global usage.jsonl.",
            "根据全局 ~/.gai/usage.jsonl 同步生成 HTML 报告。",
        ),
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help=H(
            "Open the HTML dashboard in the default browser (implies --report).",
            "用默认浏览器打开 HTML 报告（隐含 --report）。",
        ),
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=H(
            "Serve ~/.gai over local HTTP and open (implies --report; global data).",
            "用本地 HTTP 打开全局 ~/.gai 报告（隐含 --report）。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese output.",
            "使用简体中文输出；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Show LLM usage: local table by default; --report/--serve use global ~/.gai."""
    _start_trace(trace)
    try:
        if group and group not in {"action", "provider", "model", "user"}:
            tip = (
                "--group 仅支持：action / provider / model / user"
                if cn
                else "--group must be one of: action / provider / model / user"
            )
            err_console.print(f"[red]{tip}[/red]")
            raise typer.Exit(code=1)

        want_report = report or open_browser or serve
        since_dt = _parse_usage_since(since)
        if want_report:
            cap = None
            merged = ensure_global_logs_merged()
            if merged.get("usage"):
                tip = (
                    f"已合并 {merged['usage']} 条本地用量到全局日志。"
                    if cn
                    else f"Merged {merged['usage']} local usage row(s) into the global log."
                )
                console.print(f"[dim]{tip}[/dim]")
            log_path = global_usage_log_path()
            report_out = global_usage_report_path()
        else:
            cap = None if limit <= 0 else limit
            log_path = usage_log_path(scope="local")
            report_out = usage_report_path(scope="local")
        records = load_usage_records(
            path=log_path,
            limit=cap,
            since=since_dt,
            action=action,
            provider=provider,
            git_user=user,
        )
        if want_report:
            path = write_usage_report(
                records,
                chinese=cn,
                path=report_out,
                source=str(log_path),
            )
            link = path_to_file_url(path)
            msg = (
                f"已同步全局用量报告：{path}"
                if cn
                else f"Synced global usage report: {path}"
            )
            console.print(f"[green]{msg}[/green]")
            if serve:
                http_tip = (
                    "正在本地 HTTP 服务中（Ctrl+C 结束）…"
                    if cn
                    else "Serving over local HTTP (Ctrl+C to stop)…"
                )
                console.print(f"[dim]{http_tip}[/dim]")
                try:
                    serve_gai_page(path, open_browser=True, hold_seconds=3600)
                except KeyboardInterrupt:
                    console.print("\n已停止服务。" if cn else "\nStopped server.")
                    raise typer.Exit(code=130) from None
            else:
                label = "浏览器打开：" if cn else "Open in browser:"
                console.print(
                    f"{label} [link={link}][cyan underline]{link}[/cyan underline][/link]"
                )
                if open_browser:
                    open_path(path, prefer_http=False)
                tip = (
                    "数据来自全局 ~/.gai；页面内可按仓库筛选。"
                    "刷新不稳时用：gai usage --serve"
                    if cn
                    else (
                        "Data is from global ~/.gai; filter by repo in the page. "
                        "If Refresh fails under file://, use: gai usage --serve"
                    )
                )
                console.print(f"[dim]{tip}[/dim]")
            if as_json:
                console.print_json(data=[r.to_dict() for r in records])
            return

        if as_json:
            console.print_json(data=[r.to_dict() for r in records])
        else:
            text = format_usage_table(records, chinese=cn, group=group)
            console.print(text)
            if not records:
                tip = (
                    f"（当前仓写入：{usage_log_path(scope='local')}；"
                    "同时会双写到全局 ~/.gai。"
                    f"跨仓报告：gai usage --report → {global_usage_report_path()}）"
                    if cn
                    else (
                        f"(local log: {usage_log_path(scope='local')}; "
                        "also dual-written to ~/.gai. "
                        f"Cross-repo dashboard: gai usage --report → {global_usage_report_path()})"
                    )
                )
                console.print(f"[dim]{tip}[/dim]")
    except PeriodError as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "guide",
    help=H(
        "Generate a local HTML user guide at .gai/guide.html (bilingual, with language toggle).",
        "生成本地 HTML 使用指南：.gai/guide.html（中英双语，页面内可切换语言）。",
    ),
)
def guide_cmd(
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Open the guide with Chinese as the initial language.",
            "以中文作为页面初始语言；页面内仍可切换到英文。",
        ),
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help=H(
            "Open the guide in the default browser.",
            "用默认浏览器打开指南。",
        ),
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=H(
            "Serve .gai over local HTTP and open the guide.",
            "用本地 HTTP 打开指南。",
        ),
    ),
) -> None:
    """Write .gai/guide.html and print a file:// link."""
    path = write_guide_html(chinese=cn)
    link = path_to_file_url(path)
    msg = (
        f"已生成使用指南：{path}"
        if cn
        else f"Wrote user guide: {path}"
    )
    console.print(f"[green]{msg}[/green]")
    if serve:
        http_tip = (
            "正在本地 HTTP 服务中（Ctrl+C 结束）…"
            if cn
            else "Serving over local HTTP (Ctrl+C to stop)…"
        )
        console.print(f"[dim]{http_tip}[/dim]")
        try:
            serve_gai_page(path, open_browser=True, hold_seconds=3600)
        except KeyboardInterrupt:
            console.print("\n已停止服务。" if cn else "\nStopped server.")
            raise typer.Exit(code=130) from None
        return
    label = "浏览器打开：" if cn else "Open in browser:"
    console.print(f"{label} [link={link}][cyan underline]{link}[/cyan underline][/link]")
    if open_browser:
        open_path(path, prefer_http=False)
    tip = (
        "带 --cn 时首屏为中文；页面内可搜命令、深链 #commit；主题/语言与用量报告共用。"
        "再次执行会覆盖同步本文件。"
        if cn
        else (
            "With --cn the page opens in Chinese. Search commands, deep-link #commit; "
            "theme/lang prefs are shared with the usage report. Re-run overwrites this file."
        )
    )
    console.print(f"[dim]{tip}[/dim]")


@app.command(
    "history",
    help=H(
        "Show gai command history (local table; --report/--serve use ~/.gai).",
        "查看 gai 命令记录（终端看当前仓；--report/--serve 用全局 ~/.gai）。",
    ),
)
def history_cmd(
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help=H(
            "Max records to show (newest first after filters; default 20).",
            "最多显示条数（过滤后取最新；默认 20）。",
        ),
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        "-s",
        help=H(
            "Only records after this time: 7d / 2w / 1m / 1y / YYYY-MM-DD / alltime.",
            "只看该时间之后：7d / 2w / 1m / 1y / YYYY-MM-DD / alltime。",
        ),
    ),
    command: Optional[str] = typer.Option(
        None,
        "--command",
        "-c",
        help=H(
            "Filter by subcommand name (e.g. commit, usage, completion).",
            "按子命令名过滤（如 commit、usage、completion）。",
        ),
    ),
    failed: bool = typer.Option(
        False,
        "--failed",
        help=H("Only show failed runs (non-zero exit).", "只显示失败的执行（非零退出码）。"),
    ),
    report: bool = typer.Option(
        False,
        "--report",
        help=H(
            "Sync HTML dashboard under ~/.gai from the global commands.jsonl.",
            "根据全局 ~/.gai/commands.jsonl 同步生成 HTML 报告。",
        ),
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help=H(
            "Open the HTML dashboard in the default browser (implies --report).",
            "用默认浏览器打开 HTML 报告（隐含 --report）。",
        ),
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=H(
            "Serve ~/.gai over local HTTP and open (implies --report; global data).",
            "用本地 HTTP 打开全局 ~/.gai 报告（隐含 --report）。",
        ),
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=H("Print records as JSON.", "以 JSON 输出记录。"),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese output.",
            "使用简体中文输出；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Show gai CLI invocations: local table by default; --report/--serve use global."""
    _start_trace(trace)
    try:
        want_report = report or open_browser or serve
        since_dt = _parse_usage_since(since)
        if want_report:
            cap = None
            merged = ensure_global_logs_merged()
            if merged.get("commands"):
                tip = (
                    f"已合并 {merged['commands']} 条本地命令记录到全局日志。"
                    if cn
                    else f"Merged {merged['commands']} local command row(s) into the global log."
                )
                console.print(f"[dim]{tip}[/dim]")
            log_path = global_command_log_path()
            report_out = global_history_report_path()
        else:
            cap = None if limit <= 0 else limit
            log_path = command_log_path(scope="local")
            report_out = history_report_path(scope="local")
        records = load_command_records(
            path=log_path,
            limit=cap,
            since=since_dt,
            command=command,
            ok=False if failed else None,
        )
        if want_report:
            path = write_history_report(
                records,
                chinese=cn,
                path=report_out,
                source=str(log_path),
            )
            link = path_to_file_url(path)
            msg = (
                f"已同步全局命令执行报告：{path}"
                if cn
                else f"Synced global command history report: {path}"
            )
            console.print(f"[green]{msg}[/green]")
            if serve:
                http_tip = (
                    "正在本地 HTTP 服务中（Ctrl+C 结束）…"
                    if cn
                    else "Serving over local HTTP (Ctrl+C to stop)…"
                )
                console.print(f"[dim]{http_tip}[/dim]")
                try:
                    serve_gai_page(path, open_browser=True, hold_seconds=3600)
                except KeyboardInterrupt:
                    console.print("\n已停止服务。" if cn else "\nStopped server.")
                    raise typer.Exit(code=130) from None
            else:
                label = "浏览器打开：" if cn else "Open in browser:"
                console.print(
                    f"{label} [link={link}][cyan underline]{link}[/cyan underline][/link]"
                )
                if open_browser:
                    open_path(path, prefer_http=False)
                tip = (
                    "数据来自全局 ~/.gai；页面内可按仓库筛选。"
                    "刷新不稳时用：gai history --serve"
                    if cn
                    else (
                        "Data is from global ~/.gai; filter by repo in the page. "
                        "If Refresh fails under file://, use: gai history --serve"
                    )
                )
                console.print(f"[dim]{tip}[/dim]")
            if as_json:
                console.print_json(data=[r.to_dict() for r in records])
            return

        if as_json:
            console.print_json(data=[r.to_dict() for r in records])
        else:
            console.print(format_command_table(records, chinese=cn))
            if not records:
                tip = (
                    f"（当前仓写入：{command_log_path(scope='local')}；"
                    "同时会双写到全局 ~/.gai（GAI_HISTORY=0 可关闭）。"
                    f"跨仓报告：gai history --report → {global_history_report_path()}）"
                    if cn
                    else (
                        f"(local log: {command_log_path(scope='local')}; "
                        "also dual-written to ~/.gai (disable with GAI_HISTORY=0). "
                        f"Cross-repo dashboard: gai history --report → {global_history_report_path()})"
                    )
                )
                console.print(f"[dim]{tip}[/dim]")
    except PeriodError as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)
