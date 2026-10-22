"""HTML IDEA Log-style branch/commit graph for ``gai graph``."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from gai.git_ops import collect_graph_snapshot
from gai.llm.history import project_root
from gai.reports.prefs import PREF_LANG, PREF_THEME, early_prefs_script
from gai.reports.urls import path_to_file_url

_GRAPH_HTML_RELATIVE = Path(".gai") / "graph-report.html"
_GRAPH_DATA_RELATIVE = Path(".gai") / "graph-data.js"
_GRAPH_APP_JS = "graph-app.js"

__all__ = [
    "graph_data_path",
    "graph_report_path",
    "path_to_file_url",
    "write_graph_report",
]


def graph_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _GRAPH_HTML_RELATIVE


def graph_data_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _GRAPH_DATA_RELATIVE


def _vendor_graph_app(dest_dir: Path) -> Path:
    """Copy packaged graph app next to the HTML report."""
    dest = dest_dir / _GRAPH_APP_JS
    try:
        src = resources.files("gai").joinpath("static", _GRAPH_APP_JS)
        with resources.as_file(src) as path:
            shutil.copyfile(path, dest)
    except (FileNotFoundError, OSError, TypeError):
        fallback = Path(__file__).resolve().parent / "static" / _GRAPH_APP_JS
        if not fallback.is_file():
            raise RuntimeError(
                f"missing {_GRAPH_APP_JS}; reinstall gai package"
            ) from None
        shutil.copyfile(fallback, dest)
    return dest


def write_graph_report(
    *,
    chinese: bool = False,
    max_count: int | None = None,
    path: Path | None = None,
) -> Path:
    """Write/overwrite ``.gai/graph-report.html`` + data + graph-app.js."""
    target = path or graph_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data_path = target.parent / _GRAPH_DATA_RELATIVE.name
    _vendor_graph_app(target.parent)

    snap = collect_graph_snapshot(max_count=max_count)
    commits = list(snap.get("commits") or [])
    branches = list(snap.get("branches") or [])
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    payload: dict[str, Any] = {
        "initialLang": "cn" if chinese else "en",
        "generated": generated,
        "branch": snap.get("branch") or "",
        "branches": branches,
        "commits": commits,
        "maxCount": snap.get("maxCount"),
        "repoName": snap.get("repoName") or "",
        "remoteName": snap.get("remoteName") or "",
        "remoteUrl": snap.get("remoteUrl") or "",
        "collapseMin": 3,
        "i18n": {
            "cn": {
                "title": "gai 分支链路图",
                "branch": "当前分支",
                "generated": "生成时间",
                "repo": "仓库",
                "remote": "远程",
                "no_remote": "（无远程）",
                "refresh": "刷新",
                "refresh_ok": "已加载最新链路图数据",
                "refresh_fail": "刷新失败：找不到 graph-data.js",
                "refresh_fail_file": "刷新失败：file:// 可能被拦截。请改用 gai graph --serve，或重新执行 gai graph。",
                "refresh_fail_http": "刷新失败：找不到 graph-data.js。请重新执行 gai graph。",
                "empty": "暂无本地分支提交。",
                "empty_filter": "所选分支没有可显示的提交。",
                "branches": "显示分支",
                "select_all": "全选",
                "select_none": "全不选",
                "select_current": "仅当前",
                "collapse_linear": "折叠线性历史",
                "expand_linear": "展开线性历史",
                "expand": "展开 {n} 个提交",
                "collapse_hint": "点击色轨箭头展开中间提交",
                "detail_title": "提交详情",
                "detail_close": "关闭",
                "detail_hash": "提交",
                "detail_author": "作者",
                "detail_date": "时间",
                "detail_parents": "父提交",
                "detail_refs": "引用",
                "detail_body": "说明",
                "detail_none": "（无）",
                "col_message": "提交说明",
                "col_author": "作者",
                "col_date": "时间",
                "col_hash": "Hash",
                "footer": "IDEA Log 风格：色轨分叉/汇合 + 提交列表。默认展开全部；悬停看摘要，点击右侧击穿详情。每次 gai graph 覆盖本文件；推荐 --serve 刷新。",
            },
            "en": {
                "title": "gai branch graph",
                "branch": "Current branch",
                "generated": "Generated",
                "repo": "Repo",
                "remote": "Remote",
                "no_remote": "(no remote)",
                "refresh": "Refresh",
                "refresh_ok": "Graph data updated",
                "refresh_fail": "Refresh failed: graph-data.js missing",
                "refresh_fail_file": "Refresh failed: browsers may block file:// reloads. Use gai graph --serve, or re-run gai graph.",
                "refresh_fail_http": "Refresh failed: graph-data.js missing. Re-run gai graph.",
                "empty": "No local-branch commits yet.",
                "empty_filter": "No commits for the selected branches.",
                "branches": "Show branches",
                "select_all": "All",
                "select_none": "None",
                "select_current": "Current only",
                "collapse_linear": "Collapse linear history",
                "expand_linear": "Expand linear history",
                "expand": "Expand {n} commits",
                "collapse_hint": "Click the lane arrow to expand folded commits",
                "detail_title": "Commit detail",
                "detail_close": "Close",
                "detail_hash": "Commit",
                "detail_author": "Author",
                "detail_date": "Date",
                "detail_parents": "Parents",
                "detail_refs": "Refs",
                "detail_body": "Message",
                "detail_none": "(none)",
                "col_message": "Message",
                "col_author": "Author",
                "col_date": "Date",
                "col_hash": "Hash",
                "footer": "IDEA Log style: metro lanes + commit table. Expanded by default; hover for summary, click for detail. Each gai graph overwrites this file; prefer --serve for refresh.",
            },
        },
    }
    data_path.write_text(
        "window.GAI_GRAPH_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    target.write_text(_render_graph_html(payload), encoding="utf-8")
    return target


def _render_graph_html(payload: dict[str, Any]) -> str:
    initial = payload.get("initialLang") or "en"
    bootstrap = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en" data-lang="{initial}" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gai graph</title>
  <script>
  {early_prefs_script(default_lang=initial, default_theme="light")}
  </script>
  <style>
    :root {{
      --bg: #f2f2f2; --fg: #000; --muted: #6c6c6c; --card: #fff;
      --line: #c6c6c6; --row-line: #e6e6e6; --accent: #3574f0;
      --hover: #edf3ff; --sel: #d4e5ff;
      --mono: "JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace;
      --ui: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      --row-h: 22px;
    }}
    html[data-theme="dark"] {{
      --bg: #1e1f22; --fg: #dfdfdf; --muted: #9a9a9a; --card: #2b2d30;
      --line: #43454a; --row-line: #3a3c40; --accent: #548af7;
      --hover: #2e4369; --sel: #2d4a75;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: var(--ui); font-size: 13px;
      background: var(--bg); color: var(--fg); line-height: 1.35;
    }}
    .chrome {{
      position: sticky; top: 0; z-index: 20;
      background: var(--card); border-bottom: 1px solid var(--line);
    }}
    header {{
      display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start;
      justify-content: space-between; padding: 10px 12px 6px;
    }}
    h1 {{ margin: 0; font-size: 15px; font-weight: 600; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .header-right {{
      display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: flex-start;
      justify-content: flex-end; text-align: right;
    }}
    .repo-meta {{ font-size: 12px; color: var(--muted); max-width: min(420px, 70vw); }}
    .repo-meta .name {{ color: var(--fg); font-weight: 600; }}
    .repo-meta .remote {{
      font-family: var(--mono); font-size: 11px; word-break: break-all; margin-top: 2px;
    }}
    .toolbar, .filter-actions {{ display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }}
    .toolbar button, .filter-actions button, .drawer-head button {{
      border: 1px solid var(--line); background: var(--card); color: var(--fg);
      border-radius: 4px; padding: 3px 8px; cursor: pointer; font: inherit; font-size: 12px;
    }}
    .toolbar button:hover, .filter-actions button:hover, .drawer-head button:hover {{
      border-color: var(--accent); background: var(--hover);
    }}
    .toolbar button:disabled {{ opacity: .55; cursor: wait; }}
    .filter-panel {{ padding: 0 12px 8px; }}
    .filter-head {{
      display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center;
      justify-content: space-between; margin-bottom: 4px;
    }}
    .filter-title {{ font-size: 12px; color: var(--muted); font-weight: 600; }}
    .branch-checks {{ display: flex; flex-wrap: wrap; gap: 6px 12px; }}
    .branch-checks label {{
      display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
      font-size: 12px; user-select: none;
    }}
    .branch-checks .dot {{ width: 8px; height: 8px; border-radius: 50%; }}
    .branch-checks label.current {{ font-weight: 600; }}
    .branch-checks input {{ accent-color: var(--accent); }}
    .layout {{
      display: grid; grid-template-columns: 1fr minmax(280px, 340px);
      gap: 0; align-items: stretch; min-height: 40vh;
    }}
    .layout.no-detail {{ grid-template-columns: 1fr; }}
    main {{ padding: 8px 10px 28px; }}
    .board {{
      background: var(--card); border: 1px solid var(--line); border-radius: 2px;
      overflow: auto; min-height: 200px;
    }}
    table.idea {{
      border-collapse: collapse; width: 100%; font-size: 12px;
    }}
    table.idea thead th {{
      position: sticky; top: 0; z-index: 5;
      background: var(--card); border-bottom: 1px solid var(--line);
      text-align: left; padding: 5px 8px; color: var(--muted); font-weight: 600;
      white-space: nowrap; font-size: 11px;
    }}
    table.idea th.graph-h {{ padding: 0; }}
    table.idea td {{
      border-bottom: 1px solid var(--row-line); padding: 0 8px; vertical-align: middle;
      height: var(--row-h); white-space: nowrap;
    }}
    table.idea tr.commit-row {{ cursor: pointer; }}
    table.idea tr.commit-row:hover {{ background: var(--hover); }}
    table.idea tr.commit-row.active {{ background: var(--sel); }}
    td.graph-cell {{
      padding: 0 !important; width: 1%; overflow: visible; position: relative;
    }}
    td.graph-cell svg.graph-svg {{ display: block; overflow: visible; }}
    .msg {{
      display: inline-flex; align-items: center; gap: 5px; max-width: 56vw;
      overflow: hidden; text-overflow: ellipsis;
    }}
    .msg .subject {{ overflow: hidden; text-overflow: ellipsis; }}
    .msg .subject.merge {{ color: var(--muted); }}
    .ref-pill {{
      display: inline-block; font-size: 10px; line-height: 14px; padding: 0 5px;
      border-radius: 3px; color: #fff; font-weight: 600; flex-shrink: 0;
    }}
    .ref-pill.head {{ background: #6e6e6e !important; }}
    .author, .date, .hash {{ color: var(--muted); font-size: 12px; }}
    .hash {{ font-family: var(--mono); font-size: 11px; }}
    .empty {{ color: var(--muted); padding: 28px; text-align: center; }}
    footer {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .toast {{
      position: fixed; right: 14px; bottom: 14px; z-index: 40;
      background: var(--card); border: 1px solid var(--line); border-radius: 6px;
      padding: 8px 12px; box-shadow: 0 6px 18px rgba(0,0,0,.14);
      display: none; max-width: min(420px, 90vw); font-size: 12px;
    }}
    .toast.show {{ display: block; }}
    #tooltip {{
      position: fixed; z-index: 50; display: none; pointer-events: none;
      background: var(--card); border: 1px solid var(--line); border-radius: 4px;
      padding: 7px 9px; box-shadow: 0 8px 22px rgba(0,0,0,.18);
      max-width: min(420px, 90vw); font-size: 12px;
    }}
    #tooltip .t-sub {{ font-weight: 600; margin-bottom: 3px; word-break: break-word; }}
    #tooltip .t-meta {{ color: var(--muted); font-family: var(--mono); font-size: 11px; }}
    .drawer {{
      border-left: 1px solid var(--line); background: var(--card);
      display: none; flex-direction: column; min-height: 100%;
      position: sticky; top: 0; max-height: 100vh; overflow: auto;
    }}
    .layout:not(.no-detail) .drawer {{ display: flex; }}
    .drawer-head {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line);
      position: sticky; top: 0; background: var(--card); z-index: 2;
    }}
    .drawer-head h2 {{ margin: 0; font-size: 13px; }}
    .drawer-body {{ padding: 10px 12px 20px; font-size: 12px; }}
    .drawer-body .k {{ color: var(--muted); font-size: 11px; margin-top: 10px; }}
    .drawer-body .v {{ margin-top: 2px; word-break: break-word; }}
    .drawer-body .v.mono {{ font-family: var(--mono); font-size: 11px; }}
    .drawer-body .parent-link {{
      color: var(--accent); cursor: pointer; text-decoration: underline;
      display: block; margin-top: 2px;
    }}
    .drawer-body pre.body {{
      white-space: pre-wrap; margin: 0; font-family: inherit; font-size: 12px;
    }}
    [data-lang="cn"] .en {{ display: none; }}
    [data-lang="en"] .cn {{ display: none; }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .drawer {{
        border-left: none; border-top: 1px solid var(--line);
        position: relative; max-height: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="chrome">
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
      <div class="header-right">
        <div class="repo-meta">
          <div><span class="cn" data-i="repo"></span><span class="en" data-i="repo"></span>:
            <span class="name" id="repo-name"></span></div>
          <div class="remote" id="repo-remote"></div>
        </div>
        <div class="toolbar">
          <button type="button" id="btn-collapse"><span class="cn" data-i="collapse_linear"></span><span class="en" data-i="collapse_linear"></span></button>
          <button type="button" id="btn-expand"><span class="cn" data-i="expand_linear"></span><span class="en" data-i="expand_linear"></span></button>
          <button type="button" id="btn-refresh"><span class="cn" data-i="refresh"></span><span class="en" data-i="refresh"></span></button>
          <button type="button" id="btn-lang">EN / 中文</button>
          <button type="button" id="btn-theme">Theme</button>
        </div>
      </div>
    </header>
    <section class="filter-panel" aria-label="branch filter">
      <div class="filter-head">
        <div class="filter-title"><span class="cn" data-i="branches"></span><span class="en" data-i="branches"></span></div>
        <div class="filter-actions">
          <button type="button" id="btn-all"><span class="cn" data-i="select_all"></span><span class="en" data-i="select_all"></span></button>
          <button type="button" id="btn-none"><span class="cn" data-i="select_none"></span><span class="en" data-i="select_none"></span></button>
          <button type="button" id="btn-current"><span class="cn" data-i="select_current"></span><span class="en" data-i="select_current"></span></button>
        </div>
      </div>
      <div class="branch-checks" id="branch-checks"></div>
    </section>
  </div>
  <main>
    <div class="layout no-detail" id="layout">
      <div class="board">
        <div class="empty" id="empty" hidden><span id="empty-text"></span></div>
        <table class="idea" id="graph-table" hidden>
          <colgroup>
            <col class="graph-col" />
            <col />
            <col />
            <col />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th class="graph-h"></th>
              <th><span class="cn" data-i="col_message"></span><span class="en" data-i="col_message"></span></th>
              <th><span class="cn" data-i="col_author"></span><span class="en" data-i="col_author"></span></th>
              <th><span class="cn" data-i="col_date"></span><span class="en" data-i="col_date"></span></th>
              <th><span class="cn" data-i="col_hash"></span><span class="en" data-i="col_hash"></span></th>
            </tr>
          </thead>
          <tbody id="graph-body"></tbody>
        </table>
      </div>
      <aside class="drawer" id="drawer" aria-label="commit detail">
        <div class="drawer-head">
          <h2><span class="cn" data-i="detail_title"></span><span class="en" data-i="detail_title"></span></h2>
          <button type="button" id="btn-close-detail"><span class="cn" data-i="detail_close"></span><span class="en" data-i="detail_close"></span></button>
        </div>
        <div class="drawer-body" id="drawer-body"></div>
      </aside>
    </div>
    <footer>
      <span class="cn" data-i="footer"></span><span class="en" data-i="footer"></span>
    </footer>
  </main>
  <div id="tooltip" role="tooltip"></div>
  <div class="toast" id="toast" role="status"></div>
  <script id="gai-graph-bootstrap" type="application/json">{bootstrap}</script>
  <script src="graph-data.js"></script>
  <script src="{_GRAPH_APP_JS}"></script>
  <script>
  GaiGraphApp.createApp({{
    prefLang: "{PREF_LANG}",
    prefTheme: "{PREF_THEME}"
  }});
  </script>
</body>
</html>
"""
