"""HTML ECharts node-link branch/commit graph for ``gai graph``."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from gai.git_ops import collect_graph_snapshot
from gai.llm.history import project_root
from gai.llm.usage_report import path_to_file_url
from gai.web_prefs import PREF_LANG, PREF_THEME, early_prefs_script

_GRAPH_HTML_RELATIVE = Path(".gai") / "graph-report.html"
_GRAPH_DATA_RELATIVE = Path(".gai") / "graph-data.js"
_GRAPH_APP_JS = "graph-app.js"
_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"

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
                "echarts_fail": "ECharts 加载失败，请检查网络/CDN，或使用 gai graph --serve。",
                "branches": "显示分支",
                "select_all": "全选",
                "select_none": "全不选",
                "select_current": "仅当前",
                "collapse_linear": "折叠线性节点",
                "expand_linear": "展开线性节点",
                "fit": "重置视图",
                "expand": "展开 {n} 个提交",
                "collapse_hint": "双击带 ▾ 的节点，或在详情里展开中间提交",
                "detail_title": "提交详情",
                "detail_close": "关闭",
                "detail_hash": "提交",
                "detail_author": "作者",
                "detail_date": "时间",
                "detail_parents": "父提交",
                "detail_refs": "引用",
                "detail_body": "说明",
                "detail_none": "（无）",
                "hint": "默认展开约 12 个节点间距 · 滚轮缩放/拖拽平移 · 悬停摘要 · 点击详情",
                "footer": "ECharts 节点连边图：默认展开；节点详情仅悬停/点击显示。每次 gai graph 覆盖本文件；推荐 --serve 刷新。",
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
                "echarts_fail": "Failed to load ECharts. Check network/CDN, or use gai graph --serve.",
                "branches": "Show branches",
                "select_all": "All",
                "select_none": "None",
                "select_current": "Current only",
                "collapse_linear": "Collapse linear nodes",
                "expand_linear": "Expand linear nodes",
                "fit": "Reset view",
                "expand": "Expand {n} commits",
                "collapse_hint": "Double-click a ▾ node, or expand from the detail panel",
                "detail_title": "Commit detail",
                "detail_close": "Close",
                "detail_hash": "Commit",
                "detail_author": "Author",
                "detail_date": "Date",
                "detail_parents": "Parents",
                "detail_refs": "Refs",
                "detail_body": "Message",
                "detail_none": "(none)",
                "hint": "Default: spaced ~12 commits · scroll zoom / drag pan · hover summary · click details",
                "footer": "ECharts node-link graph: expanded by default; node details only on hover/click. Each gai graph overwrites this file; prefer --serve for refresh.",
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
      --bg: #eef1f6; --fg: #1a1d23; --muted: #5c6570; --card: #fff;
      --line: #d0d7e2; --accent: #3574f0; --hover: #edf3ff;
      --mono: "JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace;
      --ui: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      --chart-min: min(72vh, 820px);
    }}
    html[data-theme="dark"] {{
      --bg: #12151a; --fg: #e8eaed; --muted: #9aa3ad; --card: #1b2028;
      --line: #2c3440; --accent: #548af7; --hover: #243044;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0; font-family: var(--ui); font-size: 13px;
      background: var(--bg); color: var(--fg); line-height: 1.35;
      display: flex; flex-direction: column; min-height: 100%;
    }}
    .chrome {{
      flex: 0 0 auto; z-index: 20;
      background: var(--card); border-bottom: 1px solid var(--line);
    }}
    header {{
      display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start;
      justify-content: space-between; padding: 10px 14px 6px;
    }}
    h1 {{ margin: 0; font-size: 16px; font-weight: 650; letter-spacing: .02em; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
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
      border-radius: 6px; padding: 4px 9px; cursor: pointer; font: inherit; font-size: 12px;
    }}
    .toolbar button:hover, .filter-actions button:hover, .drawer-head button:hover {{
      border-color: var(--accent); background: var(--hover);
    }}
    .toolbar button:disabled {{ opacity: .55; cursor: wait; }}
    .filter-panel {{ padding: 0 14px 8px; }}
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
    .branch-checks .dot {{ width: 9px; height: 9px; border-radius: 50%; }}
    .branch-checks label.current {{ font-weight: 600; }}
    .branch-checks input {{ accent-color: var(--accent); }}
    main {{
      flex: 1 1 auto; display: flex; flex-direction: column;
      padding: 10px 12px 12px; min-height: 0;
    }}
    .layout {{
      flex: 1 1 auto; display: grid; grid-template-columns: 1fr minmax(280px, 340px);
      gap: 0; min-height: var(--chart-min); align-items: stretch;
    }}
    .layout.no-detail {{ grid-template-columns: 1fr; }}
    .board {{
      background: var(--card); border: 1px solid var(--line); border-radius: 10px;
      position: relative; min-height: var(--chart-min); overflow: hidden;
      box-shadow: 0 10px 28px rgba(20, 30, 50, .06);
    }}
    #graph-chart {{
      width: 100%; height: 100%; min-height: var(--chart-min);
      touch-action: none; cursor: grab;
    }}
    #graph-chart:active {{ cursor: grabbing; }}
    .chart-hint {{
      position: absolute; left: 12px; bottom: 10px; z-index: 2;
      color: var(--muted); font-size: 11px; pointer-events: none;
      background: color-mix(in srgb, var(--card) 82%, transparent);
      padding: 3px 8px; border-radius: 999px; border: 1px solid var(--line);
    }}
    .empty {{
      color: var(--muted); padding: 48px 28px; text-align: center;
      position: absolute; inset: 0; display: none; align-items: center; justify-content: center;
      pointer-events: none; z-index: 1;
    }}
    .empty:not([hidden]) {{ display: flex; pointer-events: auto; }}
    footer {{ margin-top: 8px; color: var(--muted); font-size: 12px; flex: 0 0 auto; }}
    .toast {{
      position: fixed; right: 14px; bottom: 14px; z-index: 40;
      background: var(--card); border: 1px solid var(--line); border-radius: 8px;
      padding: 8px 12px; box-shadow: 0 6px 18px rgba(0,0,0,.14);
      display: none; max-width: min(420px, 90vw); font-size: 12px;
    }}
    .toast.show {{ display: block; }}
    .drawer {{
      border: 1px solid var(--line); border-left: none; background: var(--card);
      display: none; flex-direction: column; border-radius: 0 10px 10px 0;
      max-height: calc(var(--chart-min) + 2px); overflow: auto;
    }}
    .layout:not(.no-detail) .drawer {{ display: flex; }}
    .layout:not(.no-detail) .board {{ border-radius: 10px 0 0 10px; }}
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
    .ref-pill {{
      display: inline-block; font-size: 10px; line-height: 14px; padding: 0 5px;
      border-radius: 3px; color: #fff; font-weight: 600; margin-right: 3px;
    }}
    .ref-pill.head {{ background: #6e6e6e !important; }}
    [data-lang="cn"] .en {{ display: none; }}
    [data-lang="en"] .cn {{ display: none; }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .drawer {{
        border-left: 1px solid var(--line); border-radius: 10px; margin-top: 8px;
        max-height: none;
      }}
      .layout:not(.no-detail) .board {{ border-radius: 10px; }}
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
          <button type="button" id="btn-fit"><span class="cn" data-i="fit"></span><span class="en" data-i="fit"></span></button>
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
        <div id="graph-chart" aria-label="commit graph"></div>
        <div class="chart-hint"><span class="cn" data-i="hint"></span><span class="en" data-i="hint"></span></div>
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
  <div class="toast" id="toast" role="status"></div>
  <script id="gai-graph-bootstrap" type="application/json">{bootstrap}</script>
  <script src="{_ECHARTS_CDN}"></script>
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
