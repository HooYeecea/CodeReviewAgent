"""gai status / gai log / gai graph — git views with pretty / HTML reports."""

from __future__ import annotations

from typing import Optional

import typer

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
)
from gai.git_ops import GitError, log_plain, status_plain
from gai.git_views import (
    path_to_file_url,
    render_pretty_log,
    render_pretty_status,
    write_log_report,
)
from gai.graph_report import write_graph_report
from gai.help_i18n import H
from gai.local_serve import open_path, serve_gai_page


@app.command(
    "status",
    help=H(
        "Show git status (optional Rich pretty view).",
        "查看 git status（可选 Rich 美化输出）。",
    ),
)
def status_cmd(
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-p",
        help=H(
            "Pretty Rich table grouped by staged / unstaged / untracked.",
            "用 Rich 表格按已暂存 / 未暂存 / 未跟踪分组展示。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese labels.",
            "使用简体中文标签；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Wrap ``git status``; ``--pretty`` uses a structured Rich view."""
    _start_trace(trace)
    try:
        if pretty:
            render_pretty_status(console, chinese=cn)
        else:
            text = status_plain()
            console.print(text if text else ("(clean)" if not cn else "（干净）"))
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "log",
    help=H(
        "Show git log (pretty / graph / HTML under .gai).",
        "查看 git log（美化 / 拓扑图 / 在 .gai 生成 HTML）。",
    ),
)
def log_cmd(
    max_count: Optional[int] = typer.Option(
        None,
        "--max-count",
        "-n",
        help=H(
            "Limit to N commits; omit to show all.",
            "限制为 N 条；省略则显示全部提交。",
        ),
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-p",
        help=H(
            "Pretty Rich table (or styled graph panel with --graph).",
            "Rich 表格美化（与 --graph 联用时为带样式的拓扑面板）。",
        ),
    ),
    graph: bool = typer.Option(
        False,
        "--graph",
        "-g",
        help=H(
            "Show commit topology (git log --graph).",
            "显示提交拓扑（git log --graph）。",
        ),
    ),
    as_html: bool = typer.Option(
        False,
        "--html",
        help=H(
            "Write/overwrite .gai/log-report.html with the latest snapshot.",
            "将最新快照写入并覆盖 .gai/log-report.html。",
        ),
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help=H(
            "Open the HTML report in the default browser (implies --html).",
            "用默认浏览器打开 HTML 报告（隐含 --html）。",
        ),
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=H(
            "Serve .gai over local HTTP and open the log page (implies --html).",
            "用本地 HTTP 打开日志页（隐含 --html）。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese labels / HTML initial language.",
            "使用简体中文标签；HTML 以中文为初始语言。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Wrap ``git log`` with optional pretty / graph / HTML views."""
    _start_trace(trace)
    try:
        want_html = as_html or open_browser or serve
        n: int | None
        if max_count is None:
            n = None
        else:
            n = max(1, int(max_count))

        if want_html:
            path = write_log_report(chinese=cn, max_count=n, graph=graph)
            link = path_to_file_url(path)
            msg = (
                f"已更新提交记录页：{path}"
                if cn
                else f"Updated log report: {path}"
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
            console.print(
                f"{label} [link={link}][cyan underline]{link}[/cyan underline][/link]"
            )
            if open_browser:
                open_path(path, prefer_http=False)
            tip = (
                "每次 --html 会覆盖同文件；刷新不稳时用：gai log --html --serve"
                if cn
                else "Each --html overwrites the same file; if Refresh is flaky use: gai log --html --serve"
            )
            console.print(f"[dim]{tip}[/dim]")
            return

        if pretty:
            render_pretty_log(console, chinese=cn, max_count=n, graph=graph)
        else:
            text = log_plain(max_count=n, graph=graph)
            if text:
                console.print(text)
            else:
                console.print("[yellow]" + ("暂无提交。" if cn else "No commits yet.") + "[/yellow]")
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


@app.command(
    "graph",
    help=H(
        "Write an IDE-like branch/commit graph HTML under .gai (opens by default).",
        "在 .gai 生成 IDE 风格的分支/提交链路 HTML（默认打开浏览器）。",
    ),
)
def graph_cmd(
    max_count: Optional[int] = typer.Option(
        None,
        "--max-count",
        "-n",
        help=H(
            "Limit to N commits across local branches; omit for all.",
            "限制本地分支合计提交条数；省略则全部。",
        ),
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help=H(
            "Open the graph HTML in the default browser (default: open).",
            "用默认浏览器打开链路图（默认打开）。",
        ),
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=H(
            "Serve .gai over local HTTP and open the graph page (best for Refresh).",
            "用本地 HTTP 打开链路图（刷新更稳）。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese labels / HTML initial language.",
            "使用简体中文标签；HTML 以中文为初始语言。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Generate/overwrite ``.gai/graph-report.html`` for the current repository."""
    _start_trace(trace)
    try:
        n: int | None
        if max_count is None:
            n = None
        else:
            n = max(1, int(max_count))

        path = write_graph_report(chinese=cn, max_count=n)
        link = path_to_file_url(path)
        msg = (
            f"已更新分支链路图：{path}"
            if cn
            else f"Updated branch graph: {path}"
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
        console.print(
            f"{label} [link={link}][cyan underline]{link}[/cyan underline][/link]"
        )
        if open_browser:
            open_path(path, prefer_http=False)
        tip = (
            "每次执行会覆盖同文件；页面可点「刷新」。刷新不稳时用：gai graph --serve --cn"
            if cn
            else "Each run overwrites the same file; use Refresh on the page. If flaky: gai graph --serve"
        )
        console.print(f"[dim]{tip}[/dim]")
    except typer.Exit:
        raise
    except (GitError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)
