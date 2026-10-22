"""Pretty terminal views and HTML report for ``gai status`` / ``gai log``."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gai.git_ops import (
    ChangeEntry,
    GitError,
    LogEntry,
    collect_log_entries,
    current_branch_name,
    get_current_branch,
    list_change_entries,
    list_local_branches,
    log_graph_text,
)
from gai.llm.history import project_root
from gai.reports.prefs import PREF_LANG, PREF_THEME, early_prefs_script
from gai.reports.urls import path_to_file_url

_LOG_HTML_RELATIVE = Path(".gai") / "log-report.html"

# Manual ASCII grid only: Unicode box chars are East-Asian Ambiguous and often
# render double-width on Windows CJK terminals, so any resize looks shattered.
_LOG_HASH_W = 8
_LOG_AUTHOR_W = 14
_LOG_WHEN_W = 16
# 5×'|' + 2 spaces padding × 4 columns
_LOG_TABLE_OVERHEAD = 5 + 8
# Prefer stacked layout below this terminal width (still correct, just no grid).
_LOG_GRID_MIN_WIDTH = 72


def _char_width(ch: str) -> int:
    """Display columns for one code point (CJK wide = 2; ASCII/box-safe = 1)."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _display_width(s: str) -> int:
    return sum(_char_width(ch) for ch in s)


def _truncate_display(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if _display_width(s) <= width:
        return s
    ell = "..."
    ell_w = 3 if width >= 3 else width
    limit = width - ell_w
    out: list[str] = []
    used = 0
    for ch in s:
        cw = _char_width(ch)
        if used + cw > limit:
            break
        out.append(ch)
        used += cw
    return "".join(out) + ell[:ell_w]


def _pad_display(s: str, width: int) -> str:
    """Pad / truncate so the string occupies exactly ``width`` display columns."""
    s = _truncate_display(s, width)
    return s + " " * (width - _display_width(s))


def _wrap_display_lines(s: str, width: int) -> list[str]:
    """Wrap ``s`` by display width; prefer breaking at spaces when possible."""
    if width < 1:
        width = 1
    chunks: list[str] = []
    buf: list[str] = []
    buf_w = 0
    last_space = -1
    for ch in s:
        cw = _char_width(ch)
        if buf and buf_w + cw > width:
            if last_space >= 0:
                chunks.append("".join(buf[:last_space]))
                rest = buf[last_space + 1 :]
                buf = rest + [ch]
                buf_w = _display_width("".join(buf))
                last_space = next(
                    (i for i, c in enumerate(buf) if c in " \t"),
                    -1,
                )
            else:
                chunks.append("".join(buf))
                buf, buf_w, last_space = [ch], cw, -1
        else:
            buf.append(ch)
            buf_w += cw
            if ch in " \t":
                last_space = len(buf) - 1
    if buf:
        chunks.append("".join(buf))
    return chunks


def _subject_cells(subject: str, decorations: str, width: int) -> list[Text]:
    """Pre-wrap subject into display-padded Text cells (one per visual line)."""
    body_lines = _wrap_display_lines(subject, width) or [""]
    deco = (decorations or "").strip()
    cells: list[Text] = []
    if deco and body_lines and _display_width(body_lines[-1]) + 1 + _display_width(deco) <= width:
        for ln in body_lines[:-1]:
            cells.append(Text(_pad_display(ln, width)))
        last = Text(body_lines[-1])
        last.append(" ")
        last.append(deco, style="dim")
        last.append(" " * (width - _display_width(f"{body_lines[-1]} {deco}")))
        cells.append(last)
        return cells
    for ln in body_lines:
        cells.append(Text(_pad_display(ln, width)))
    if deco:
        for ln in _wrap_display_lines(deco, width):
            cells.append(Text(_pad_display(ln, width), style="dim"))
    return cells


def _rule_ascii(widths: list[int], left: str, mid: str, right: str, fill: str = "-") -> str:
    parts = [fill * (w + 2) for w in widths]
    return left + mid.join(parts) + right


def _term_width(console: Console) -> int:
    """Usable columns for layout (1-col margin; respects explicit Console width)."""
    # Rich ignores constructor ``width`` on dumb terminals unless ``height`` is
    # also set; prefer the explicit value when present.
    if console._width is not None:  # noqa: SLF001 — intentional
        w = console._width
        if console.legacy_windows and console._height is not None:  # noqa: SLF001
            w -= 1
    else:
        w = console.width or 80
    return max(40, w - 1)


def _print_line(
    console: Console,
    line: Text | str,
    *,
    style: str | None = None,
    width: int | None = None,
) -> None:
    """Print one row; never soft-wrap (wrapping shatters column borders)."""
    kwargs: dict[str, Any] = {
        "overflow": "ignore",
        "crop": False,
        "soft_wrap": False,
    }
    if width is not None:
        kwargs["width"] = width
    if isinstance(line, str):
        console.print(line, style=style, **kwargs)
    else:
        console.print(line, **kwargs)


def _print_log_grid(
    console: Console,
    *,
    title: str,
    headers: list[str],
    entries_rows: list[list[list[Text | str]]],
    widths: list[int],
) -> None:
    """ASCII bordered table; every line is exactly table-width (narrow chars only)."""
    border = "cyan"
    top = _rule_ascii(widths, "+", "+", "+", "-")
    sep = _rule_ascii(widths, "+", "+", "+", "-")
    bot = _rule_ascii(widths, "+", "+", "+", "-")
    total = sum(widths) + _LOG_TABLE_OVERHEAD
    tpad = max(0, total - _display_width(title))
    _print_line(console, " " * (tpad // 2) + title, style="bold", width=total)
    _print_line(console, top, style=border, width=total)

    head = Text()
    head.append("|", style=border)
    for h, w in zip(headers, widths, strict=True):
        head.append(" ")
        head.append(_pad_display(h, w), style="bold")
        head.append(" ")
        head.append("|", style=border)
    _print_line(console, head, width=total)
    _print_line(console, sep, style=border, width=total)

    for r_i, commit_lines in enumerate(entries_rows):
        for cells in commit_lines:
            line = Text()
            line.append("|", style=border)
            for cell, w in zip(cells, widths, strict=True):
                if isinstance(cell, Text):
                    piece = cell
                    pad_n = w - _display_width(piece.plain)
                    if pad_n > 0:
                        piece = piece.copy()
                        piece.append(" " * pad_n)
                else:
                    piece = Text(_pad_display(str(cell), w))
                line.append(" ")
                line.append_text(piece)
                line.append(" ")
                line.append("|", style=border)
            _print_line(console, line, width=total)
        if r_i < len(entries_rows) - 1:
            _print_line(console, sep, style=border, width=total)
    _print_line(console, bot, style=border, width=total)


def _print_log_stacked(
    console: Console,
    *,
    title: str,
    entries: list[LogEntry],
    term_w: int,
) -> None:
    """Narrow-terminal fallback: hash/meta on one line, wrapped subject below."""
    _print_line(console, title, style="bold", width=term_w)
    body_w = max(16, term_w - 2)
    for i, e in enumerate(entries):
        meta = Text()
        meta.append(e.short, style="cyan")
        meta.append("  ")
        meta.append(_truncate_display(e.author, 18), style="green")
        meta.append("  ")
        meta.append(_fmt_date(e.date), style="dim")
        _print_line(console, meta, width=term_w)
        for cell in _subject_cells(e.subject, e.decorations or "", body_w):
            line = Text("  ")
            clipped = cell.copy()
            pad = len(cell.plain) - len(cell.plain.rstrip(" "))
            if pad:
                clipped.right_crop(pad)
            line.append_text(clipped)
            _print_line(console, line, width=term_w)
        if i < len(entries) - 1:
            _print_line(
                console,
                "-" * min(term_w, body_w + 2),
                style="cyan",
                width=term_w,
            )


__all__ = [
    "log_report_path",
    "path_to_file_url",
    "render_pretty_log",
    "render_pretty_status",
    "write_log_report",
]


def log_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _LOG_HTML_RELATIVE


def _status_label(entry: ChangeEntry, *, chinese: bool) -> str:
    if entry.untracked:
        return "未跟踪" if chinese else "untracked"
    if entry.staged and entry.unstaged:
        return "暂存+未暂存" if chinese else "staged+unstaged"
    if entry.staged:
        return "已暂存" if chinese else "staged"
    if entry.unstaged:
        return "未暂存" if chinese else "unstaged"
    return f"{entry.index}{entry.worktree}"


def render_pretty_status(
    console: Console,
    *,
    chinese: bool = False,
) -> None:
    """Rich status: branch + grouped change table."""
    branch = get_current_branch()
    entries = list_change_entries()
    header = (
        f"当前分支：[bold cyan]{branch}[/bold cyan]"
        if chinese
        else f"On branch [bold cyan]{branch}[/bold cyan]"
    )
    console.print(header)

    if not entries:
        tip = "工作区干净，无未提交变更。" if chinese else "Working tree clean."
        console.print(f"[green]{tip}[/green]")
        return

    staged = [e for e in entries if e.staged]
    unstaged = [e for e in entries if e.unstaged and not e.untracked]
    untracked = [e for e in entries if e.untracked]

    def _section(title: str, rows: list[ChangeEntry], style: str) -> None:
        if not rows:
            return
        table = Table(title=title, show_header=True, header_style="bold", border_style=style)
        table.add_column("状态" if chinese else "State", style=style, no_wrap=True)
        table.add_column("路径" if chinese else "Path")
        for e in rows:
            table.add_row(_status_label(e, chinese=chinese), e.path)
        console.print(table)

    _section("已暂存" if chinese else "Staged", staged, "green")
    _section("未暂存" if chinese else "Unstaged", unstaged, "yellow")
    _section("未跟踪" if chinese else "Untracked", untracked, "cyan")

    summary = (
        f"共 {len(entries)} 个路径（暂存 {len(staged)} / 未暂存 {len(unstaged)} / 未跟踪 {len(untracked)}）"
        if chinese
        else (
            f"{len(entries)} path(s) "
            f"(staged {len(staged)} / unstaged {len(unstaged)} / untracked {len(untracked)})"
        )
    )
    console.print(f"[dim]{summary}[/dim]")


def _fmt_date(iso: str) -> str:
    text = (iso or "").strip()
    if not text:
        return ""
    try:
        # 2024-01-02T03:04:05+08:00 or Z
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def render_pretty_log(
    console: Console,
    *,
    chinese: bool = False,
    max_count: int | None = None,
    graph: bool = False,
) -> None:
    """Rich log table, or colored graph text when ``graph`` is set."""
    branch = get_current_branch()
    if max_count is None:
        title = (
            f"提交记录 · {branch}（全部）"
            if chinese
            else f"Commits · {branch} (all)"
        )
    else:
        title = (
            f"提交记录 · {branch}（最近 {max_count}）"
            if chinese
            else f"Commits · {branch} (last {max_count})"
        )
    if graph:
        text = log_graph_text(max_count=max_count)
        if not text:
            tip = "暂无提交。" if chinese else "No commits yet."
            console.print(f"[yellow]{tip}[/yellow]")
            return
        try:
            body: Text | str = Text.from_ansi(text)
        except Exception:  # noqa: BLE001 — plain fallback if ANSI parse fails
            body = text
        console.print(Panel(body, title=title, border_style="cyan"))
        return

    entries = collect_log_entries(max_count=max_count)
    if not entries:
        tip = "暂无提交。" if chinese else "No commits yet."
        console.print(f"[yellow]{tip}[/yellow]")
        return

    term_w = _term_width(console)
    if term_w < _LOG_GRID_MIN_WIDTH:
        _print_log_stacked(console, title=title, entries=entries, term_w=term_w)
        return

    subject_w = max(
        16,
        term_w - _LOG_HASH_W - _LOG_AUTHOR_W - _LOG_WHEN_W - _LOG_TABLE_OVERHEAD,
    )
    widths = [_LOG_HASH_W, subject_w, _LOG_AUTHOR_W, _LOG_WHEN_W]
    headers = [
        "Hash",
        "说明" if chinese else "Subject",
        "作者" if chinese else "Author",
        "时间" if chinese else "When",
    ]
    empty_hash = " " * _LOG_HASH_W
    empty_author = " " * _LOG_AUTHOR_W
    empty_when = " " * _LOG_WHEN_W
    commits: list[list[list[Text | str]]] = []
    for e in entries:
        subj_lines = _subject_cells(e.subject, e.decorations or "", subject_w)
        author = _pad_display(e.author, _LOG_AUTHOR_W)
        when = _pad_display(_fmt_date(e.date), _LOG_WHEN_W)
        short = _pad_display(e.short, _LOG_HASH_W)
        visual: list[list[Text | str]] = []
        for i, subj in enumerate(subj_lines):
            if i == 0:
                visual.append(
                    [
                        Text(short, style="cyan"),
                        subj,
                        Text(author, style="green"),
                        Text(when, style="dim"),
                    ]
                )
            else:
                visual.append([empty_hash, subj, empty_author, empty_when])
        commits.append(visual)
    _print_log_grid(
        console,
        title=title,
        headers=headers,
        entries_rows=commits,
        widths=widths,
    )


def write_log_report(
    *,
    chinese: bool = False,
    max_count: int | None = None,
    graph: bool = False,
    path: Path | None = None,
) -> Path:
    """Write/overwrite ``.gai/log-report.html`` with the latest log snapshot.

    Embeds every local branch's commits so the HTML page can switch branches
    without regenerating (default selection = current branch).
    """
    target = path or log_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    current = current_branch_name()
    if not current or current == "HEAD":
        try:
            current = get_current_branch()
        except GitError:
            current = "HEAD"
    branches = list_local_branches()
    if current and current not in branches:
        branches = [current, *branches]
    branches = sorted(set(branches), key=lambda b: (b != current, b.lower()))

    commits_by_branch: dict[str, list[dict[str, str]]] = {}
    graph_by_branch: dict[str, str] = {}
    for name in branches:
        ref = None if name == "HEAD" else name
        try:
            entries = collect_log_entries(max_count=max_count, ref=ref)
        except GitError:
            entries = []
        commits_by_branch[name] = [e.to_dict() for e in entries]
        if graph:
            try:
                graph_by_branch[name] = log_graph_text(max_count=max_count, ref=ref)
            except GitError:
                graph_by_branch[name] = ""

    entries_current = commits_by_branch.get(current) or next(
        iter(commits_by_branch.values()),
        [],
    )
    graph_text = graph_by_branch.get(current, "") if graph else ""
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    payload: dict[str, Any] = {
        "initialLang": "cn" if chinese else "en",
        "generated": generated,
        "branch": current,
        "branches": branches,
        "commitsByBranch": commits_by_branch,
        "graphByBranch": graph_by_branch,
        "maxCount": max_count,
        "graph": bool(graph),
        "graphText": graph_text,
        "commits": entries_current,
        "i18n": {
            "cn": {
                "title": "gai 提交记录",
                "branch": "分支",
                "generated": "生成时间",
                "hash": "Hash",
                "subject": "说明",
                "author": "作者",
                "when": "时间",
                "graph": "拓扑图",
                "empty": "暂无提交。",
                "footer": "由 gai log --html 生成；每次执行会覆盖本文件。可用 gai log --html --serve 打开。页面内可切换本地分支查看。",
            },
            "en": {
                "title": "gai commit log",
                "branch": "Branch",
                "generated": "Generated",
                "hash": "Hash",
                "subject": "Subject",
                "author": "Author",
                "when": "When",
                "graph": "Graph",
                "empty": "No commits yet.",
                "footer": "Generated by gai log --html; each run overwrites this file. Open with gai log --html --serve. Switch local branches on the page.",
            },
        },
    }
    target.write_text(_render_log_html(payload), encoding="utf-8")
    return target


def _render_log_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    initial = payload["initialLang"]
    return f"""<!DOCTYPE html>
<html lang="en" data-lang="{initial}" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gai log</title>
  <script>
  {early_prefs_script(default_lang=initial, default_theme="light")}
  </script>
  <style>
    :root {{
      --bg: #f6f7f9; --fg: #1a1d23; --muted: #5c6570; --card: #fff;
      --line: #d8dde3; --accent: #0b6e4f; --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    html[data-theme="dark"] {{
      --bg: #12151a; --fg: #e8eaed; --muted: #9aa3ad; --card: #1b2028; --line: #2c3440; --accent: #3dcf9a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg); color: var(--fg); line-height: 1.5;
    }}
    header {{
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
      justify-content: space-between; padding: 20px 24px; border-bottom: 1px solid var(--line);
      background: var(--card);
    }}
    h1 {{ margin: 0; font-size: 1.35rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }}
    .branch-picker {{
      display: inline-flex; align-items: center; gap: 8px;
      color: var(--fg); font-size: 0.9rem;
    }}
    .branch-picker select {{
      border: 1px solid var(--line); background: var(--bg); color: var(--fg);
      border-radius: 8px; padding: 4px 8px; min-width: 10rem; max-width: 18rem;
      font: inherit; cursor: pointer;
    }}
    .toolbar button {{
      margin-left: 8px; border: 1px solid var(--line); background: var(--bg);
      color: var(--fg); border-radius: 8px; padding: 6px 10px; cursor: pointer;
    }}
    main {{ padding: 20px 24px 40px; max-width: 1100px; margin: 0 auto; }}
    table {{
      width: 100%; border-collapse: collapse; background: var(--card);
      border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
      table-layout: fixed;
    }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ font-size: 0.85rem; color: var(--muted); background: color-mix(in srgb, var(--card) 80%, var(--bg)); }}
    tr:last-child td {{ border-bottom: none; }}
    th:nth-child(1), td.hash {{ width: 7.5rem; }}
    th:nth-child(3), td.author {{ width: 8.5rem; }}
    th:nth-child(4), td.when {{ width: 10.5rem; }}
    code, .hash, pre {{ font-family: var(--mono); font-size: 0.85rem; }}
    .hash {{ color: var(--accent); white-space: nowrap; }}
    .author, .when {{ white-space: nowrap; }}
    td.subject {{ overflow-wrap: anywhere; word-break: break-word; }}
    .deco {{ color: var(--muted); margin-left: 6px; }}
    pre.graph {{
      white-space: pre-wrap; background: var(--card); border: 1px solid var(--line);
      border-radius: 12px; padding: 14px 16px; overflow: auto;
    }}
    footer {{ margin-top: 18px; color: var(--muted); font-size: 0.85rem; }}
    .empty {{ color: var(--muted); padding: 24px; }}
    [data-lang="cn"] .en {{ display: none; }}
    [data-lang="en"] .cn {{ display: none; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1><span class="cn" data-i="title"></span><span class="en" data-i="title"></span></h1>
      <div class="meta">
        <label class="branch-picker">
          <span class="cn" data-i="branch"></span><span class="en" data-i="branch"></span>
          <select id="branch-select" aria-label="branch"></select>
        </label>
        <span>· <span class="cn" data-i="generated"></span><span class="en" data-i="generated"></span>:
        <span id="generated"></span></span>
      </div>
    </div>
    <div class="toolbar">
      <button type="button" id="btn-lang">EN / 中文</button>
      <button type="button" id="btn-theme">Theme</button>
    </div>
  </header>
  <main>
    <section id="graph-section" hidden>
      <h2><span class="cn" data-i="graph"></span><span class="en" data-i="graph"></span></h2>
      <pre class="graph" id="graph"></pre>
    </section>
    <section>
      <div id="empty" class="empty" hidden>
        <span class="cn" data-i="empty"></span><span class="en" data-i="empty"></span>
      </div>
      <table id="tbl" hidden>
        <thead>
          <tr>
            <th><span class="cn" data-i="hash"></span><span class="en" data-i="hash"></span></th>
            <th><span class="cn" data-i="subject"></span><span class="en" data-i="subject"></span></th>
            <th><span class="cn" data-i="author"></span><span class="en" data-i="author"></span></th>
            <th><span class="cn" data-i="when"></span><span class="en" data-i="when"></span></th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </section>
    <footer>
      <span class="cn" data-i="footer"></span><span class="en" data-i="footer"></span>
    </footer>
  </main>
  <script id="gai-log-data" type="application/json">{data_json}</script>
  <script>
  (function() {{
    var raw = document.getElementById('gai-log-data').textContent;
    var data = JSON.parse(raw);
    function applyI18n() {{
      var lang = document.documentElement.getAttribute('data-lang') || 'en';
      var dict = (data.i18n && data.i18n[lang]) || data.i18n.en;
      document.querySelectorAll('[data-i]').forEach(function(el) {{
        var key = el.getAttribute('data-i');
        if (dict[key]) el.textContent = dict[key];
      }});
    }}
    function fmtDate(iso) {{
      if (!iso) return '';
      try {{
        var d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        var p = function(n) {{ return String(n).padStart(2, '0'); }};
        return d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate())
          + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
      }} catch (e) {{ return iso; }}
    }}
    document.getElementById('generated').textContent = data.generated || '';
    var empty = document.getElementById('empty');
    var tbl = document.getElementById('tbl');
    var tbody = document.getElementById('tbody');
    var branchSelect = document.getElementById('branch-select');
    var byBranch = data.commitsByBranch || {{}};
    var graphByBranch = data.graphByBranch || {{}};
    var branchNames = data.branches && data.branches.length
      ? data.branches.slice()
      : Object.keys(byBranch);
    if (!branchNames.length && data.branch) branchNames = [data.branch];
    if (!Object.keys(byBranch).length && data.commits) {{
      byBranch[data.branch || 'HEAD'] = data.commits;
    }}
    branchNames.forEach(function(name) {{
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === data.branch) opt.selected = true;
      branchSelect.appendChild(opt);
    }});
    function escapeHtml(s) {{
      return String(s).replace(/[&<>"']/g, function(ch) {{
        return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[ch];
      }});
    }}
    function renderBranch(name) {{
      var commits = byBranch[name] || [];
      tbody.innerHTML = '';
      if (!commits.length) {{
        empty.hidden = false;
        tbl.hidden = true;
      }} else {{
        empty.hidden = true;
        tbl.hidden = false;
        commits.forEach(function(c) {{
          var tr = document.createElement('tr');
          var deco = c.decorations ? '<span class="deco">' + escapeHtml(c.decorations) + '</span>' : '';
          tr.innerHTML =
            '<td class="hash">' + escapeHtml(c.short || '') + '</td>' +
            '<td class="subject">' + escapeHtml(c.subject || '') + deco + '</td>' +
            '<td class="author">' + escapeHtml(c.author || '') + '</td>' +
            '<td class="when">' + escapeHtml(fmtDate(c.date || '')) + '</td>';
          tbody.appendChild(tr);
        }});
      }}
      var sec = document.getElementById('graph-section');
      var gtext = data.graph ? (graphByBranch[name] || data.graphText || '') : '';
      if (data.graph && gtext) {{
        sec.hidden = false;
        document.getElementById('graph').textContent = gtext;
      }} else {{
        sec.hidden = true;
        document.getElementById('graph').textContent = '';
      }}
    }}
    branchSelect.addEventListener('change', function() {{
      renderBranch(branchSelect.value);
    }});
    renderBranch(branchSelect.value || data.branch || branchNames[0] || '');
    document.getElementById('btn-lang').addEventListener('click', function() {{
      var cur = document.documentElement.getAttribute('data-lang') === 'cn' ? 'en' : 'cn';
      document.documentElement.setAttribute('data-lang', cur);
      document.documentElement.lang = cur === 'cn' ? 'zh-CN' : 'en';
      try {{ localStorage.setItem('{PREF_LANG}', cur); }} catch (e) {{}}
      applyI18n();
    }});
    document.getElementById('btn-theme').addEventListener('click', function() {{
      var cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', cur);
      try {{ localStorage.setItem('{PREF_THEME}', cur); }} catch (e) {{}}
    }});
    applyI18n();
  }})();
  </script>
</body>
</html>
"""
