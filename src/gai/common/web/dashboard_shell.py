"""Shared HTML chrome for usage / history ECharts dashboards."""

from __future__ import annotations

import html
from typing import Mapping

from gai.common.web.prefs import early_prefs_script
from gai.common.web.shell_css import DASHBOARD_CSS


def dashboard_head(
    *,
    title: str,
    data_script: str,
    chinese: bool,
    initial_lang: str | None = None,
) -> str:
    """``<!DOCTYPE>`` through ``</head><body>`` (ECharts + shared CSS)."""
    lang = initial_lang or ("cn" if chinese else "en")
    html_lang = "zh-CN" if lang == "cn" else "en"
    safe_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="{html_lang}" class="view-all" data-lang="{lang}" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title}</title>
<script>
{early_prefs_script(default_lang=lang, default_theme="dark")}
</script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
<script src="{html.escape(data_script)}"></script>
<style>
{DASHBOARD_CSS}</style>
</head>
<body>
"""


def dashboard_chrome(
    *,
    brand: str,
    title: str,
    badge: str,
    t: Mapping[str, str],
    project_dd_label: str | None = None,
) -> str:
    """Hero + toolbar + project filter row (shared by usage/history)."""
    safe_title = html.escape(title)
    dd_label = html.escape(project_dd_label or t.get("project_all", "All projects"))
    return f"""  <div class="shell">
    <header class="hero">
      <div>
        <div class="brand">{html.escape(brand)}</div>
        <h1 data-i="title">{safe_title}</h1>
        <div class="meta" id="meta-line"></div>
      </div>
      <div class="badge">{html.escape(badge)}</div>
    </header>

    <div class="toolbar">
      <button type="button" class="btn-refresh" id="btn-refresh" data-i="refresh">刷新</button>
      <button type="button" class="btn-export" id="btn-export-csv" data-i="export_csv">导出 CSV</button>
      <div class="seg" role="group" aria-label="Theme">
        <button type="button" id="btn-theme-light" data-i="theme_light">日间</button>
        <button type="button" id="btn-theme-dark" data-i="theme_dark">夜间</button>
      </div>
      <div class="seg" role="group" aria-label="Language">
        <button type="button" id="btn-lang-cn">中文</button>
        <button type="button" id="btn-lang-en">EN</button>
      </div>
    </div>

    <div class="filters">
      <label id="project-filter-label" data-i="project_filter">{html.escape(t.get("project_filter", ""))}</label>
      <div class="dd" id="project-dd">
        <button type="button" class="dd-trigger" id="project-dd-btn"
                aria-haspopup="listbox" aria-expanded="false"
                aria-labelledby="project-filter-label project-dd-label">
          <span class="dd-ico" aria-hidden="true">⌘</span>
          <span class="dd-label" id="project-dd-label">{dd_label}</span>
          <span class="dd-caret" aria-hidden="true"></span>
        </button>
        <div class="dd-menu" id="project-dd-menu" role="listbox" aria-labelledby="project-filter-label">
        </div>
      </div>
      <span class="meta" id="project-hint" data-i="hint_project">{html.escape(t.get("hint_project", ""))}</span>
    </div>
"""


def dashboard_footer_and_toast(*, footer: str) -> str:
    """Close main shell + toast host (before ``<script>``)."""
    return f"""    <footer data-i="footer">{html.escape(footer)}</footer>
  </div>
  <div class="toast" id="toast"></div>
"""


def dashboard_boot_js(
    *,
    i18n_js: str,
    datasets_global: str,
    data_file: str,
    loader_id: str,
) -> str:
    """Shared I18N/DATASETS bootstrap + toast/esc/themeColors helpers."""
    return f"""
const I18N_ALL = {i18n_js};
let lang = document.documentElement.getAttribute('data-lang') === 'cn' ? 'cn' : 'en';
let I18N = I18N_ALL[lang] || I18N_ALL.en;
let DATASETS = window.{datasets_global} || {{ all: {{}}, projects: [], by_project: {{}}, default_project: '__all__' }};
let A = DATASETS.all || {{}};
let currentProject = DATASETS.default_project || '__all__';
let currentTrend = (A && A.default_trend) || 'today';
let chartHandles = [];
let toastTimer = null;
let dropdownBound = false;
const TABLE_PAGE_SIZE = 25;
let tablePage = 0;

function themeColors() {{
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? ['#0284c7', '#0f766e', '#7c3aed', '#d97706', '#db2777', '#2563eb', '#e11d48', '#0d9488']
    : ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#fb7185', '#2dd4bf'];
}}

function showToast(msg) {{
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}}

function esc(s) {{
  return String(s)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}}

function ink() {{
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#e8eef8';
}}
function muted() {{
  return getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#94a3b8';
}}

function applyViewScope() {{
  const isAll = currentProject === '__all__';
  document.documentElement.classList.toggle('view-all', isAll);
  document.documentElement.classList.toggle('view-repo', !isAll);
  const hint = document.getElementById('project-hint');
  if (hint) hint.textContent = isAll ? I18N.hint_project_all : I18N.hint_project_repo;
}}

function refreshHint() {{
  const viaHttp = location.protocol === 'http:' || location.protocol === 'https:';
  if (viaHttp) return I18N.refresh_fail_http || I18N.refresh_fail || 'Failed';
  return I18N.refresh_fail_file || I18N.refresh_fail || 'Failed';
}}

function refreshData() {{
  const btn = document.getElementById('btn-refresh');
  if (btn) {{
    btn.disabled = true;
    btn.textContent = I18N.refreshing || '...';
  }}
  const old = document.getElementById('{loader_id}');
  if (old) old.remove();
  const s = document.createElement('script');
  s.id = '{loader_id}';
  s.src = '{data_file}?t=' + Date.now();
  s.onload = () => {{
    applyDatasets(window.{datasets_global});
    showToast(I18N.refresh_ok || 'OK');
    if (btn) {{
      btn.disabled = false;
      btn.textContent = I18N.refresh;
    }}
  }};
  s.onerror = () => {{
    showToast(refreshHint());
    if (btn) {{
      btn.disabled = false;
      btn.textContent = I18N.refresh;
    }}
  }};
  document.head.appendChild(s);
}}
""".strip()
