"""Shared browser preference keys and helpers for gai HTML pages."""

from __future__ import annotations

# Keep guide.html and usage-report.html in sync.
PREF_THEME = "gai-ui-theme"
PREF_LANG = "gai-ui-lang"


def early_prefs_script(*, default_lang: str = "en", default_theme: str = "dark") -> str:
    """Inline <script> that applies saved theme/lang before first paint."""
    lang = "cn" if default_lang == "cn" else "en"
    theme = "light" if default_theme == "light" else "dark"
    return f"""
(function(){{
  try {{
    var th = localStorage.getItem('{PREF_THEME}');
    if (th !== 'light' && th !== 'dark') th = '{theme}';
    document.documentElement.setAttribute('data-theme', th);
    var lg = localStorage.getItem('{PREF_LANG}');
    if (lg !== 'cn' && lg !== 'en') lg = '{lang}';
    document.documentElement.setAttribute('data-lang', lg);
    document.documentElement.lang = lg === 'cn' ? 'zh-CN' : 'en';
  }} catch (e) {{
    document.documentElement.setAttribute('data-theme', '{theme}');
    document.documentElement.setAttribute('data-lang', '{lang}');
  }}
}})();
""".strip()
