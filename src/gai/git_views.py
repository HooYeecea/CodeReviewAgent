"""Pretty terminal views and HTML report for ``gai status`` / ``gai log``."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gai.git_ops import (
    ChangeEntry,
    collect_log_entries,
    get_current_branch,
    list_change_entries,
    log_graph_text,
)
from gai.llm.history import project_root
from gai.llm.usage_report import path_to_file_url
from gai.web_prefs import PREF_LANG, PREF_THEME, early_prefs_script

_LOG_HTML_RELATIVE = Path(".gai") / "log-report.html"

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

    table = Table(title=title, show_header=True, header_style="bold", border_style="cyan")
    table.add_column("Hash", style="cyan", no_wrap=True)
    table.add_column("说明" if chinese else "Subject")
    table.add_column("作者" if chinese else "Author", style="green")
    table.add_column("时间" if chinese else "When", style="dim", no_wrap=True)
    for e in entries:
        subject = e.subject
        if e.decorations:
            subject = f"{subject} [dim]{e.decorations}[/dim]"
        table.add_row(e.short, subject, e.author, _fmt_date(e.date))
    console.print(table)


def write_log_report(
    *,
    chinese: bool = False,
    max_count: int | None = None,
    graph: bool = False,
    path: Path | None = None,
) -> Path:
    """Write/overwrite ``.gai/log-report.html`` with the latest log snapshot."""
    target = path or log_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = get_current_branch()
    entries = collect_log_entries(max_count=max_count)
    graph_text = log_graph_text(max_count=max_count) if graph else ""
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    payload: dict[str, Any] = {
        "initialLang": "cn" if chinese else "en",
        "generated": generated,
        "branch": branch,
        "maxCount": max_count,
        "graph": bool(graph),
        "graphText": graph_text,
        "commits": [e.to_dict() for e in entries],
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
                "footer": "由 gai log --html 生成；每次执行会覆盖本文件。可用 gai log --html --serve 打开。",
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
                "footer": "Generated by gai log --html; each run overwrites this file. Open with gai log --html --serve.",
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
    .meta {{ color: var(--muted); font-size: 0.9rem; }}
    .toolbar button {{
      margin-left: 8px; border: 1px solid var(--line); background: var(--bg);
      color: var(--fg); border-radius: 8px; padding: 6px 10px; cursor: pointer;
    }}
    main {{ padding: 20px 24px 40px; max-width: 1100px; margin: 0 auto; }}
    table {{
      width: 100%; border-collapse: collapse; background: var(--card);
      border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
    }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ font-size: 0.85rem; color: var(--muted); background: color-mix(in srgb, var(--card) 80%, var(--bg)); }}
    tr:last-child td {{ border-bottom: none; }}
    code, .hash, pre {{ font-family: var(--mono); font-size: 0.85rem; }}
    .hash {{ color: var(--accent); }}
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
        <span class="cn" data-i="branch"></span><span class="en" data-i="branch"></span>:
        <strong id="branch"></strong>
        · <span class="cn" data-i="generated"></span><span class="en" data-i="generated"></span>:
        <span id="generated"></span>
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
    document.getElementById('branch').textContent = data.branch || '';
    document.getElementById('generated').textContent = data.generated || '';
    var commits = data.commits || [];
    var empty = document.getElementById('empty');
    var tbl = document.getElementById('tbl');
    var tbody = document.getElementById('tbody');
    if (!commits.length) {{
      empty.hidden = false;
    }} else {{
      tbl.hidden = false;
      commits.forEach(function(c) {{
        var tr = document.createElement('tr');
        var deco = c.decorations ? '<span class="deco">' + escapeHtml(c.decorations) + '</span>' : '';
        tr.innerHTML =
          '<td class="hash">' + escapeHtml(c.short || '') + '</td>' +
          '<td>' + escapeHtml(c.subject || '') + deco + '</td>' +
          '<td>' + escapeHtml(c.author || '') + '</td>' +
          '<td>' + escapeHtml(fmtDate(c.date || '')) + '</td>';
        tbody.appendChild(tr);
      }});
    }}
    if (data.graph && data.graphText) {{
      var sec = document.getElementById('graph-section');
      sec.hidden = false;
      document.getElementById('graph').textContent = data.graphText;
    }}
    function escapeHtml(s) {{
      return String(s).replace(/[&<>"']/g, function(ch) {{
        return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[ch];
      }});
    }}
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
