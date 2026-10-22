"""Shared dashboard JS snippets for usage / history HTML reports."""

from __future__ import annotations

from gai.common.web.prefs import PREF_LANG, PREF_THEME


def dashboard_theme_lang_js() -> str:
    """Theme + language helpers (expects applyStaticI18n / rebuildProjectMenu / renderDashboard)."""
    return f"""
function currentTheme() {{
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}}

function applyTheme(theme) {{
  document.documentElement.setAttribute('data-theme', theme);
  try {{ localStorage.setItem('{PREF_THEME}', theme); }} catch (e) {{}}
  document.getElementById('btn-theme-light').classList.toggle('active', theme === 'light');
  document.getElementById('btn-theme-dark').classList.toggle('active', theme === 'dark');
}}

function setTheme(next, animate) {{
  const theme = next === 'light' ? 'light' : 'dark';
  if (theme === currentTheme()) {{
    applyTheme(theme);
    renderDashboard();
    return;
  }}
  const run = () => {{
    applyTheme(theme);
    renderDashboard();
  }};
  if (
    animate !== false &&
    document.startViewTransition &&
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ) {{
    document.startViewTransition(run);
    return;
  }}
  run();
}}

function setLang(next) {{
  lang = next === 'cn' ? 'cn' : 'en';
  I18N = I18N_ALL[lang] || I18N_ALL.en;
  document.documentElement.setAttribute('data-lang', lang);
  document.documentElement.lang = lang === 'cn' ? 'zh-CN' : 'en';
  try {{ localStorage.setItem('{PREF_LANG}', lang); }} catch (e) {{}}
  document.getElementById('btn-lang-cn').classList.toggle('active', lang === 'cn');
  document.getElementById('btn-lang-en').classList.toggle('active', lang === 'en');
  applyStaticI18n();
  rebuildProjectMenu();
  renderDashboard();
}}
""".strip()
