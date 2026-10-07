"""Build a fixed project HTML dashboard from usage.jsonl (ECharts)."""

from __future__ import annotations

import html
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from gai.llm.history import (
    UsageRecord,
    load_usage_records,
    project_root,
    summarize_records,
    usage_log_path,
)
from gai.web_prefs import PREF_LANG, PREF_THEME, early_prefs_script

_REPORT_RELATIVE = Path(".gai") / "usage-report.html"
_DATA_RELATIVE = Path(".gai") / "usage-data.js"
# Avoid rewriting usage-data.js on every rapid LLM call burst.
_SYNC_MIN_INTERVAL_SEC = 2.0


def usage_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _REPORT_RELATIVE


def usage_data_path(cwd: Path | None = None) -> Path:
    """Companion datasets file loaded by the HTML report (refreshable)."""
    return project_root(cwd) / _DATA_RELATIVE


def write_usage_data_js(
    datasets: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    """Write ``window.__GAI_USAGE_DATASETS__ = ...`` for the HTML dashboard."""
    target = path or usage_data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(datasets, ensure_ascii=False)
    # Keep as one assignment so the report can reload with a cache-busting query.
    target.write_text(
        "window.__GAI_USAGE_DATASETS__ = " + payload + ";\n",
        encoding="utf-8",
    )
    return target


def sync_usage_data_file(
    *,
    log_path: Path | None = None,
    force: bool = False,
    ensure_html: bool = True,
) -> Path | None:
    """Rebuild usage-data.js from usage.jsonl (best-effort; never raises).

    Throttles rewrites within ``_SYNC_MIN_INTERVAL_SEC`` unless ``force``.
    When ``ensure_html`` is True and the report HTML is missing, creates a
    shell page so first-time users can open the dashboard after any LLM call.
    """
    try:
        data_path = (
            log_path.parent / "usage-data.js" if log_path is not None else usage_data_path()
        )
        if (
            not force
            and data_path.is_file()
            and (time.time() - data_path.stat().st_mtime) < _SYNC_MIN_INTERVAL_SEC
        ):
            return data_path
        records = load_usage_records(path=log_path)
        datasets = build_report_datasets(records)
        written = write_usage_data_js(datasets, path=data_path)
        if ensure_html:
            html_path = data_path.parent / "usage-report.html"
            if not html_path.is_file():
                # Create the HTML shell once; data file already written above.
                html_path.write_text(
                    render_usage_report_html(datasets, chinese=False),
                    encoding="utf-8",
                )
        return written
    except Exception:
        return None


def path_to_file_url(path: Path) -> str:
    """Return a browser-openable ``file://`` URL for a local path."""
    resolved = path.resolve()
    # pathlib.as_uri() already produces a correct file:// URL on Windows/POSIX.
    try:
        return resolved.as_uri()
    except ValueError:
        # Extremely rare non-absolute edge case
        text = str(resolved).replace("\\", "/")
        if not text.startswith("/"):
            text = "/" + text
        return "file://" + quote(text, safe="/:")


def build_usage_analytics(records: list[UsageRecord]) -> dict[str, Any]:
    """Aggregate records into chart-friendly structures."""
    summary = summarize_records(records)
    ok_count = sum(1 for r in records if r.ok is True)
    fail_count = sum(1 for r in records if r.ok is False)
    unknown_count = sum(1 for r in records if r.ok is None)
    durations = [r.duration_ms for r in records if r.duration_ms is not None]
    avg_ms = int(sum(durations) / len(durations)) if durations else None

    by_action: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_provider: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_user: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_branch: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_repo: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    model_durations: dict[str, list[int]] = defaultdict(list)
    # heatmap: (branch, action) -> tokens
    heat: dict[tuple[str, str], int] = defaultdict(int)
    # heatmap: (repo, action) -> tokens
    heat_repo: dict[tuple[str, str], int] = defaultdict(int)

    for rec in records:
        tok = rec.total_tokens or 0

        action = rec.action_detail or rec.action or "(unknown)"
        by_action[action]["calls"] += 1
        by_action[action]["tokens"] += tok

        provider = rec.provider_name or rec.provider or "(unknown)"
        by_provider[provider]["calls"] += 1
        by_provider[provider]["tokens"] += tok

        model = rec.model or "(unknown)"
        by_model[model]["calls"] += 1
        by_model[model]["tokens"] += tok
        if rec.duration_ms is not None:
            model_durations[model].append(rec.duration_ms)

        if rec.git_user and rec.git_email:
            user = f"{rec.git_user} <{rec.git_email}>"
        else:
            user = rec.git_user or rec.git_email or "(unknown)"
        by_user[user]["calls"] += 1
        by_user[user]["tokens"] += tok

        branch = (rec.branch or "").strip() or "(unknown)"
        by_branch[branch]["calls"] += 1
        by_branch[branch]["tokens"] += tok
        heat[(branch, action)] += tok

        repo = _project_key(rec)
        by_repo[repo]["calls"] += 1
        by_repo[repo]["tokens"] += tok
        heat_repo[(repo, action)] += tok

    recent = list(reversed(records[-100:]))
    trends = build_trend_series(records)

    branches = sorted(by_branch.keys(), key=lambda b: (-by_branch[b]["tokens"], b))
    actions = sorted(by_action.keys(), key=lambda a: (-by_action[a]["tokens"], a))
    repos = sorted(by_repo.keys(), key=lambda r: (-by_repo[r]["tokens"], r))
    heatmap_data = [
        [actions.index(a), branches.index(b), heat[(b, a)]]
        for b, a in heat
        if heat[(b, a)] > 0
    ]
    heatmap_repo_data = [
        [actions.index(a), repos.index(r), heat_repo[(r, a)]]
        for r, a in heat_repo
        if heat_repo[(r, a)] > 0 and a in actions and r in repos
    ]

    duration_by_model = _duration_series(model_durations)

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": str(usage_log_path()),
        "totals": {
            "calls": summary.calls,
            "tokens": summary.total_tokens,
            "tokens_known": summary.total_known,
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
            "ok": ok_count,
            "fail": fail_count,
            "unknown": unknown_count,
            "avg_duration_ms": avg_ms,
        },
        # Backward-compatible alias: all calendar days.
        "by_day": trends.get("all_days") or {"labels": [], "calls": [], "tokens": []},
        "trends": trends,
        "default_trend": "today",
        "by_action": _series(by_action),
        "by_provider": _series(by_provider),
        "by_model": _series(by_model),
        "by_user": _series(by_user),
        "by_branch": _series(by_branch),
        "by_repo": _series(by_repo),
        "by_status": {
            "labels": ["ok", "fail", "unknown"],
            "calls": [ok_count, fail_count, unknown_count],
        },
        "token_split": {
            "labels": ["prompt", "completion"],
            "tokens": [summary.prompt_tokens, summary.completion_tokens],
        },
        "duration_by_model": duration_by_model,
        "heatmap": {
            "branches": branches,
            "actions": actions,
            "data": heatmap_data,
        },
        "heatmap_repo": {
            "repos": repos,
            "actions": actions,
            "data": heatmap_repo_data,
        },
        "recent": [r.to_dict() for r in recent],
    }


def build_report_datasets(records: list[UsageRecord]) -> dict[str, Any]:
    """Precompute analytics for all projects and each repo_name."""
    labels: dict[str, str] = {}
    for rec in records:
        key = _project_key(rec)
        labels[key] = _project_label(rec)

    by_project: dict[str, dict[str, Any]] = {}
    for key in labels:
        subset = [r for r in records if _project_key(r) == key]
        by_project[key] = build_usage_analytics(subset)

    return {
        "all": build_usage_analytics(records),
        "by_project": by_project,
        "projects": [
            {"id": key, "label": labels[key]}
            for key in sorted(labels.keys())
        ],
        "default_project": "__all__",
    }


def _project_key(rec: UsageRecord) -> str:
    return (rec.repo_name or "").strip() or "(unknown)"


def _project_label(rec: UsageRecord) -> str:
    """Display label: repo bound with remote (remote is not a separate filter)."""
    key = _project_key(rec)
    if rec.remote_name:
        return f"{key} · {rec.remote_name}"
    return key


def build_trend_series(
    records: list[UsageRecord],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, list[Any]]]:
    """Build switchable trend buckets for the main time chart."""
    now = now or datetime.now(timezone.utc).astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone()

    parsed: list[tuple[datetime, int]] = []
    for rec in records:
        dt = _parse_ts_dt(rec.ts)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        else:
            dt = dt.astimezone(now.tzinfo)
        parsed.append((dt, rec.total_tokens or 0))

    today = now.date()
    # today: hours 00:00 .. current hour
    today_labels = [f"{h:02d}:00" for h in range(0, now.hour + 1)]
    today_tokens = [0] * len(today_labels)
    today_calls = [0] * len(today_labels)
    for dt, tok in parsed:
        if dt.date() != today:
            continue
        idx = dt.hour
        if 0 <= idx < len(today_labels):
            today_calls[idx] += 1
            today_tokens[idx] += tok

    last7 = _rolling_day_series(parsed, today=today, days=7)
    last15 = _rolling_day_series(parsed, today=today, days=15)
    all_days = _bucket_series(
        parsed,
        key_fn=lambda dt: dt.date().isoformat(),
        fill_keys=_all_day_keys(parsed),
    )
    by_week = _bucket_series(
        parsed,
        key_fn=lambda dt: f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}",
    )
    by_month = _bucket_series(parsed, key_fn=lambda dt: dt.strftime("%Y-%m"))
    by_year = _bucket_series(parsed, key_fn=lambda dt: dt.strftime("%Y"))

    return {
        "today": {
            "labels": today_labels,
            "calls": today_calls,
            "tokens": today_tokens,
            "title_key": "trend_today",
        },
        "last7": {**last7, "title_key": "trend_last7"},
        "last15": {**last15, "title_key": "trend_last15"},
        "week": {**by_week, "title_key": "trend_week"},
        "month": {**by_month, "title_key": "trend_month"},
        "year": {**by_year, "title_key": "trend_year"},
        "all_days": {**all_days, "title_key": "trend_all_days"},
    }


def write_usage_report(
    records: list[UsageRecord],
    *,
    chinese: bool = False,
    path: Path | None = None,
) -> Path:
    """Overwrite the fixed HTML report with data synced from usage.jsonl."""
    target = path or usage_report_path()
    datasets = build_report_datasets(records)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_usage_data_js(datasets, path=target.parent / "usage-data.js")
    target.write_text(
        render_usage_report_html(datasets, chinese=chinese),
        encoding="utf-8",
    )
    return target


def render_usage_report_html(datasets: dict[str, Any], *, chinese: bool = False) -> str:
    """HTML dashboard powered by ECharts; datasets load from usage-data.js."""
    t = _i18n(chinese)
    i18n_bundle = {"cn": _i18n(True), "en": _i18n(False)}
    i18n_js = json.dumps(i18n_bundle, ensure_ascii=False)
    initial_lang = "cn" if chinese else "en"
    title = html.escape(t["title"])
    # Initial KPI placeholders; JS fills from usage-data.js on load/refresh.
    project_dd_label = html.escape(t["project_all"])

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if chinese else 'en'}" class="view-all" data-lang="{initial_lang}" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<script>
{early_prefs_script(default_lang=initial_lang, default_theme="dark")}
</script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
<script src="usage-data.js"></script>
<style>
  :root, html[data-theme="dark"] {{
    --bg0: #07101d;
    --bg1: #101a2c;
    --panel: linear-gradient(165deg, rgba(36, 48, 72, .96), rgba(18, 28, 46, .96));
    --panel-flat: rgba(22, 32, 51, 0.94);
    --panel-border: rgba(148, 163, 184, 0.22);
    --panel-shine: rgba(255, 255, 255, 0.08);
    --text: #e8eef8;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent2: #a78bfa;
    --ok: #34d399;
    --fail: #f87171;
    --warn: #fbbf24;
    --top-bg: rgba(7, 16, 29, .72);
    --seg-bg: rgba(15, 23, 42, .7);
    --seg-btn: linear-gradient(180deg, rgba(40, 54, 78, .95), rgba(18, 28, 46, .95));
    --seg-btn-text: #cbd5e1;
    --seg-active-bg: linear-gradient(180deg, rgba(56,189,248,.28), rgba(56,189,248,.1));
    --seg-active-text: #bae6fd;
    --on-ink: #0b1220;
    --chart-well: linear-gradient(180deg, rgba(8,14,26,.45), rgba(8,14,26,.18));
    --chart-well-border: rgba(148,163,184,.16);
    --chart-well-shadow: 0 1px 0 rgba(255,255,255,.05) inset, 0 12px 28px rgba(0,0,0,.28) inset, 0 -1px 0 rgba(0,0,0,.35) inset;
    --chart-muted: #94a3b8;
    --chart-label: #e2e8f0;
    --chart-line: #475569;
    --chart-split: rgba(148,163,184,.14);
    --chart-pie-border: #121a2b;
    --chart-symbol-stroke: #0b1220;
    --table-bg: rgba(8, 14, 26, .28);
    --table-head: rgba(18, 26, 43, .95);
    --badge-bg: linear-gradient(180deg, rgba(56,189,248,.16), rgba(56,189,248,.06));
    --badge-border: rgba(56,189,248,.35);
    --badge-text: #bae6fd;
    --shadow-deep: 0 22px 48px rgba(0, 0, 0, .45), 0 2px 0 rgba(255,255,255,.04) inset;
    --shadow-lift: 0 10px 28px rgba(0, 0, 0, .35), 0 1px 0 rgba(255,255,255,.06) inset, 0 -1px 0 rgba(0,0,0,.35) inset;
    --glow-a: rgba(56,189,248,.18);
    --glow-b: rgba(167,139,250,.16);
    --heat-0: #0f172a;
    --heat-1: #1d4ed8;
    --heat-2: #38bdf8;
    --heat-3: #fbbf24;
  }}
  html[data-theme="light"] {{
    --bg0: #e8eef6;
    --bg1: #f5f8fc;
    --panel: linear-gradient(165deg, #ffffff, #f2f6fb);
    --panel-flat: #ffffff;
    --panel-border: #c5d0de;
    --panel-shine: rgba(255, 255, 255, 0.95);
    --text: #0b1b33;
    --muted: #334155;
    --accent: #0f766e;
    --accent2: #0369a1;
    --ok: #047857;
    --fail: #b91c1c;
    --warn: #b45309;
    --top-bg: rgba(245, 248, 252, .92);
    --seg-bg: #ffffff;
    --seg-btn: linear-gradient(180deg, #ffffff, #e8eef6);
    --seg-btn-text: #1e3350;
    --seg-active-bg: linear-gradient(180deg, #ccfbf1, #e6fffa);
    --seg-active-text: #115e59;
    --on-ink: #ffffff;
    --chart-well: linear-gradient(180deg, #ffffff, #f1f5f9);
    --chart-well-border: #b8c5d6;
    --chart-well-shadow:
      0 1px 0 rgba(255,255,255,.98) inset,
      0 -1px 0 rgba(11,27,51,.08) inset,
      0 10px 22px rgba(11,27,51,.07) inset,
      0 8px 18px rgba(11,27,51,.07);
    --chart-muted: #1e3350;
    --chart-label: #0b1b33;
    --chart-line: #64748b;
    --chart-split: rgba(11,27,51,.12);
    --chart-pie-border: #ffffff;
    --chart-symbol-stroke: #ffffff;
    --table-bg: #f8fafc;
    --table-head: #e8eef6;
    --badge-bg: linear-gradient(180deg, #ccfbf1, #e6fffa);
    --badge-border: rgba(15,118,110,.35);
    --badge-text: #115e59;
    --shadow-deep: 0 18px 40px rgba(16,35,63,.08), 0 1px 0 rgba(255,255,255,.9) inset, 0 -1px 0 rgba(16,35,63,.05) inset;
    --shadow-lift: 0 12px 28px rgba(16,35,63,.08), 0 1px 0 rgba(255,255,255,.95) inset, 0 -1px 0 rgba(16,35,63,.06) inset;
    --glow-a: rgba(15,118,110,.10);
    --glow-b: rgba(2,132,199,.08);
    --heat-0: #eef2ff;
    --heat-1: #93c5fd;
    --heat-2: #0ea5e9;
    --heat-3: #f59e0b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    color: var(--text);
    font-family: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background:
      radial-gradient(900px 420px at 8% -8%, var(--glow-a), transparent 55%),
      radial-gradient(800px 380px at 92% 0%, var(--glow-b), transparent 50%),
      linear-gradient(180deg, var(--bg1), var(--bg0));
  }}
  @media (prefers-reduced-motion: no-preference) {{
    html.theme-ready body,
    html.theme-ready .kpi,
    html.theme-ready .card,
    html.theme-ready .filters,
    html.theme-ready .toolbar .seg,
    html.theme-ready .toolbar .seg button,
    html.theme-ready .dd-trigger,
    html.theme-ready .dd-menu {{
      transition: background .4s cubic-bezier(.22,1,.36,1), color .4s cubic-bezier(.22,1,.36,1),
        border-color .4s cubic-bezier(.22,1,.36,1), box-shadow .4s cubic-bezier(.22,1,.36,1);
    }}
    ::view-transition-old(root), ::view-transition-new(root) {{
      animation-duration: .4s;
      animation-timing-function: cubic-bezier(.22,1,.36,1);
    }}
  }}
  .shell {{
    max-width: 1240px;
    margin: 0 auto;
    padding: 28px 22px 40px;
  }}
  header.hero {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 22px;
  }}
  .brand {{
    font-size: .78rem;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 8px;
  }}
  h1 {{
    margin: 0;
    font-size: clamp(1.55rem, 2.4vw, 2rem);
    font-weight: 700;
    letter-spacing: -.02em;
  }}
  .meta {{
    margin-top: 10px;
    color: var(--muted);
    font-size: .9rem;
    line-height: 1.55;
  }}
  .badge {{
    align-self: flex-start;
    padding: 8px 12px;
    border-radius: 12px;
    border: 1px solid var(--badge-border);
    background: var(--badge-bg);
    box-shadow: var(--shadow-lift);
    color: var(--badge-text);
    font-size: .82rem;
    font-weight: 650;
    white-space: nowrap;
  }}
  .kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
    position: relative;
    z-index: 1;
  }}
  .kpi, .card, .filters {{
    position: relative;
    isolation: isolate;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 18px;
    box-shadow: var(--shadow-lift);
    backdrop-filter: blur(10px);
  }}
  .kpi, .card {{
    z-index: 1;
  }}
  /* Shine stays behind content — never wash out titles / table text. */
  .kpi::before, .card::before, .filters::before {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: 0;
    border-radius: inherit;
    pointer-events: none;
    background: linear-gradient(180deg, var(--panel-shine), transparent 42%);
    opacity: .55;
  }}
  .kpi > *, .card > *, .filters > * {{
    position: relative;
    z-index: 1;
  }}
  .kpi {{
    padding: 16px 16px 14px;
  }}
  .kpi .label {{
    color: var(--muted);
    font-size: .8rem;
    font-weight: 650;
  }}
  .kpi .value {{
    margin-top: 8px;
    font-size: 1.45rem;
    font-weight: 760;
    letter-spacing: -.02em;
    color: var(--text);
  }}
  .kpi .sub {{
    margin-top: 4px;
    color: var(--muted);
    font-size: .78rem;
    font-weight: 550;
  }}
  .value.ok {{ color: var(--ok); }}
  .value.fail {{ color: var(--fail); }}
  .grid {{
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 14px;
  }}
  .card {{
    padding: 16px 16px 12px;
    min-width: 0;
  }}
  .card.full {{ grid-column: 1 / -1; }}
  .card h2 {{
    margin: 0 0 4px;
    font-size: 1.02rem;
    font-weight: 750;
    color: var(--text);
    letter-spacing: -.01em;
  }}
  .card .hint {{
    color: var(--muted);
    font-size: .84rem;
    font-weight: 600;
    margin-bottom: 6px;
    line-height: 1.45;
  }}
  html[data-theme="light"] .card h2,
  html[data-theme="light"] .card-head h2 {{
    color: #071526;
  }}
  html[data-theme="light"] .card .hint,
  html[data-theme="light"] .kpi .label,
  html[data-theme="light"] .kpi .sub,
  html[data-theme="light"] .meta,
  html[data-theme="light"] footer,
  html[data-theme="light"] th {{
    color: #1a2f4a;
  }}
  html[data-theme="light"] td {{
    color: #0b1b33;
  }}
  html[data-theme="light"] .card::before,
  html[data-theme="light"] .kpi::before,
  html[data-theme="light"] .filters::before {{
    opacity: .28;
    background: linear-gradient(180deg, rgba(255,255,255,.7), transparent 36%);
  }}
  .card-head {{
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 6px;
  }}
  .card-head h2 {{ margin: 0 0 4px; }}
  .seg {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .seg button {{
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 999px;
    padding: 6px 11px;
    font-size: .75rem;
    cursor: pointer;
    box-shadow: var(--shadow-lift);
  }}
  .seg button:hover {{
    border-color: var(--accent);
    color: var(--accent);
    transform: translateY(-1px);
  }}
  .seg button.active {{
    background: var(--seg-active-bg);
    border-color: var(--accent);
    color: var(--seg-active-text);
    font-weight: 650;
    box-shadow: var(--shadow-lift);
  }}
  .toolbar {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    justify-content: flex-end;
    margin: 0 0 12px;
  }}
  .toolbar .seg {{
    border: 1px solid var(--panel-border);
    background: var(--seg-bg);
    border-radius: 10px;
    overflow: hidden;
    gap: 0;
    box-shadow: var(--shadow-lift);
  }}
  .toolbar .seg button {{
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    box-shadow: none;
    padding: 8px 12px;
    font-size: .78rem;
    font-weight: 600;
    transform: none;
  }}
  .toolbar .seg button:hover {{
    color: var(--accent);
    transform: none;
  }}
  .toolbar .seg button.active {{
    background: var(--text);
    color: var(--on-ink);
    border-color: transparent;
    box-shadow: none;
  }}
  .toolbar .btn-refresh {{
    border: 1px solid var(--panel-border);
    background: var(--seg-bg);
    color: var(--text);
    border-radius: 10px;
    padding: 8px 14px;
    font-size: .78rem;
    font-weight: 650;
    cursor: pointer;
    box-shadow: var(--shadow-lift);
  }}
  .toolbar .btn-refresh:hover {{
    border-color: var(--accent);
    color: var(--accent);
  }}
  .toolbar .btn-refresh:disabled {{
    opacity: .6;
    cursor: wait;
  }}
  .toolbar .btn-export {{
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 999px;
    padding: 8px 14px;
    font: inherit;
    font-weight: 650;
    cursor: pointer;
  }}
  .toolbar .btn-export:hover {{ filter: brightness(1.08); }}
  button:focus-visible, .dd-trigger:focus-visible, .seg button:focus-visible {{
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }}
  .table-tools {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: 0 0 10px;
  }}
  .pager {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }}
  .pager button {{
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 8px;
    padding: 6px 10px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }}
  .pager button:disabled {{ opacity: .45; cursor: not-allowed; }}
  .pager-meta {{ color: var(--muted); font-size: .85rem; }}
  .toast {{
    position: fixed;
    bottom: 22px;
    right: 22px;
    z-index: 80;
    padding: 10px 16px;
    border-radius: 10px;
    background: var(--text);
    color: var(--on-ink);
    font-weight: 650;
    font-size: .85rem;
    opacity: 0;
    transform: translateY(6px);
    pointer-events: none;
    transition: opacity .2s ease, transform .2s ease;
  }}
  .toast.show {{ opacity: 1; transform: none; }}
  .filters {{
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
    margin: 0 0 16px;
    padding: 14px 16px;
    z-index: 40;
    overflow: visible;
  }}
  .filters > label {{
    color: #cbd5e1;
    font-size: .84rem;
    font-weight: 600;
  }}
  .filters > .meta {{
    margin: 0;
    flex: 1 1 220px;
  }}
  .dd {{
    position: relative;
    min-width: min(320px, 100%);
    z-index: 50;
  }}
  .dd.open {{
    z-index: 60;
  }}
  .dd-trigger {{
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    padding: 11px 12px;
    color: var(--text);
    cursor: pointer;
    text-align: left;
    background: var(--seg-btn);
    box-shadow: var(--shadow-lift);
  }}
  .dd-trigger:hover {{
    border-color: var(--accent);
  }}
  .dd.open .dd-trigger {{
    border-color: var(--accent);
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent),
      var(--shadow-lift);
  }}
  .dd-ico {{
    width: 28px;
    height: 28px;
    border-radius: 9px;
    display: grid;
    place-items: center;
    background: var(--seg-active-bg);
    border: 1px solid var(--badge-border);
    box-shadow: 0 1px 0 rgba(255,255,255,.35) inset;
    color: var(--badge-text);
    font-size: .85rem;
    flex: 0 0 auto;
  }}
  .dd-label {{
    flex: 1 1 auto;
    font-size: .9rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .dd-caret {{
    width: 8px;
    height: 8px;
    border-right: 2px solid #94a3b8;
    border-bottom: 2px solid #94a3b8;
    transform: rotate(45deg);
    margin: -4px 4px 0 0;
    transition: transform .18s ease;
  }}
  .dd.open .dd-caret {{
    transform: rotate(225deg);
    margin-top: 2px;
  }}
  .dd-menu {{
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 8px);
    z-index: 70;
    display: none;
    padding: 8px;
    border-radius: 14px;
    border: 1px solid var(--panel-border);
    background: var(--panel);
    box-shadow: var(--shadow-deep);
    max-height: 280px;
    overflow: auto;
  }}
  .dd.open .dd-menu {{ display: block; }}
  .dd-item {{
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--text);
    padding: 10px 10px;
    cursor: pointer;
    text-align: left;
    font-size: .88rem;
  }}
  .dd-item:hover {{
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }}
  .dd-item.active {{
    background: var(--seg-active-bg);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent) inset;
  }}
  .dd-item-text {{ flex: 1 1 auto; }}
  .dd-check {{
    opacity: 0;
    color: #7dd3fc;
    font-size: .85rem;
  }}
  .dd-item.active .dd-check {{ opacity: 1; }}
  .dd-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: 0 0 auto;
    box-shadow: 0 0 0 3px rgba(255,255,255,.04);
  }}
  .dd-dot.all {{ background: #a78bfa; }}
  .dd-dot.repo {{ background: #38bdf8; }}
  /* all = overview across repos; repo = single-repo detail */
  html.view-all .scope-repo,
  html.view-repo .scope-all {{
    display: none !important;
  }}
  .chart {{
    width: 100%;
    height: 300px;
    border-radius: 14px;
    border: 1px solid var(--chart-well-border);
    background: var(--chart-well);
    box-shadow: var(--chart-well-shadow);
  }}
  .chart.tall {{ height: 340px; }}
  .table-wrap {{
    position: relative;
    z-index: 1;
    overflow-x: auto;
    margin-top: 8px;
    border-radius: 14px;
    border: 1px solid var(--chart-well-border);
    background: var(--table-bg);
    box-shadow: var(--chart-well-shadow);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .84rem;
    color: var(--text);
  }}
  th, td {{
    text-align: left;
    padding: 10px 8px;
    border-bottom: 1px solid var(--panel-border);
    vertical-align: top;
    color: inherit;
    opacity: 1;
  }}
  th {{
    color: var(--muted);
    font-weight: 700;
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--table-head);
  }}
  td {{
    font-weight: 500;
  }}
  tr:hover td {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}
  .pill {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: .72rem;
    font-weight: 700;
  }}
  .pill.ok {{ background: rgba(4,120,87,.14); color: var(--ok); }}
  .pill.fail {{ background: rgba(185,28,28,.12); color: var(--fail); }}
  html[data-theme="light"] .table-wrap {{
    background: #ffffff;
  }}
  html[data-theme="light"] .pill.ok {{
    background: #d1fae5;
    color: #065f46;
  }}
  html[data-theme="light"] .pill.fail {{
    background: #fee2e2;
    color: #991b1b;
  }}
  .empty {{
    display: none;
    padding: 64px 20px;
    text-align: center;
    color: var(--muted);
    background: var(--panel);
    border: 1px dashed var(--panel-border);
    border-radius: 18px;
    box-shadow: var(--shadow-lift);
  }}
  footer {{
    margin-top: 22px;
    color: var(--muted);
    font-size: .78rem;
  }}
  @media (max-width: 920px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .chart, .chart.tall {{ height: 280px; }}
    .dd {{ min-width: 100%; }}
  }}
</style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <div class="brand">GAI USAGE</div>
        <h1 data-i="title">{title}</h1>
        <div class="meta" id="meta-line"></div>
      </div>
      <div class="badge">ECharts · .gai/usage-report.html</div>
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
      <label id="project-filter-label" data-i="project_filter">{t['project_filter']}</label>
      <div class="dd" id="project-dd">
        <button type="button" class="dd-trigger" id="project-dd-btn"
                aria-haspopup="listbox" aria-expanded="false"
                aria-labelledby="project-filter-label project-dd-label">
          <span class="dd-ico" aria-hidden="true">⌘</span>
          <span class="dd-label" id="project-dd-label">{project_dd_label}</span>
          <span class="dd-caret" aria-hidden="true"></span>
        </button>
        <div class="dd-menu" id="project-dd-menu" role="listbox" aria-labelledby="project-filter-label">
        </div>
      </div>
      <span class="meta" id="project-hint" data-i="hint_project">{html.escape(t['hint_project'])}</span>
    </div>

    <div class="empty" id="empty" data-i="empty">{html.escape(t['empty'])}</div>

    <div id="content">
      <section class="kpis">
        <div class="kpi">
          <div class="label" data-i="calls">{t['calls']}</div>
          <div class="value" id="kpi-calls">0</div>
        </div>
        <div class="kpi">
          <div class="label" data-i="tokens">{t['tokens']}</div>
          <div class="value" id="kpi-tokens">0</div>
          <div class="sub" id="kpi-token-sub"></div>
        </div>
        <div class="kpi">
          <div class="label" data-i="ok">{t['ok']}</div>
          <div class="value ok" id="kpi-ok">0</div>
        </div>
        <div class="kpi">
          <div class="label" data-i="fail">{t['fail']}</div>
          <div class="value fail" id="kpi-fail">0</div>
        </div>
        <div class="kpi">
          <div class="label" data-i="avg_ms">{t['avg_ms']}</div>
          <div class="value" id="kpi-ms">—</div>
        </div>
      </section>

      <section class="grid">
        <div class="card full">
          <div class="card-head">
            <div>
              <h2 id="trend-title" data-i="trend_title">{t['trend_title']}</h2>
              <div class="hint" id="trend-hint" data-i="hint_today">{t['hint_today']}</div>
            </div>
            <div class="seg" id="trend-seg" role="tablist">
              <button type="button" data-mode="today" class="active" data-i="seg_today">{t['seg_today']}</button>
              <button type="button" data-mode="last7" data-i="seg_last7">{t['seg_last7']}</button>
              <button type="button" data-mode="last15" data-i="seg_last15">{t['seg_last15']}</button>
              <button type="button" data-mode="week" data-i="seg_week">{t['seg_week']}</button>
              <button type="button" data-mode="month" data-i="seg_month">{t['seg_month']}</button>
              <button type="button" data-mode="year" data-i="seg_year">{t['seg_year']}</button>
              <button type="button" data-mode="all_days" data-i="seg_all_days">{t['seg_all_days']}</button>
            </div>
          </div>
          <div id="chart-day" class="chart tall"></div>
        </div>
        <div class="card scope-all">
          <h2 data-i="by_repo">{t['by_repo']}</h2>
          <div class="hint" data-i="hint_repo">{t['hint_repo']}</div>
          <div id="chart-repo" class="chart"></div>
        </div>
        <div class="card scope-repo">
          <h2 data-i="by_branch">{t['by_branch']}</h2>
          <div class="hint" data-i="hint_branch_repo">{t['hint_branch_repo']}</div>
          <div id="chart-branch" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="by_status">{t['by_status']}</h2>
          <div class="hint" data-i="hint_status">{t['hint_status']}</div>
          <div id="chart-status" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="token_split">{t['token_split']}</h2>
          <div class="hint" data-i="hint_split">{t['hint_split']}</div>
          <div id="chart-split" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="duration_by_model">{t['duration_by_model']}</h2>
          <div class="hint" data-i="hint_duration">{t['hint_duration']}</div>
          <div id="chart-duration" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="by_action">{t['by_action']}</h2>
          <div class="hint" data-i="hint_pie">{t['hint_pie']}</div>
          <div id="chart-action" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="by_provider">{t['by_provider']}</h2>
          <div class="hint" data-i="hint_pie">{t['hint_pie']}</div>
          <div id="chart-provider" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="by_model">{t['by_model']}</h2>
          <div class="hint" data-i="hint_bar">{t['hint_bar']}</div>
          <div id="chart-model" class="chart"></div>
        </div>
        <div class="card">
          <h2 data-i="by_user">{t['by_user']}</h2>
          <div class="hint" data-i="hint_bar">{t['hint_bar']}</div>
          <div id="chart-user" class="chart"></div>
        </div>
        <div class="card full scope-all">
          <h2 data-i="heatmap_repo">{t['heatmap_repo']}</h2>
          <div class="hint" data-i="hint_heat_repo">{t['hint_heat_repo']}</div>
          <div id="chart-heat-repo" class="chart tall"></div>
        </div>
        <div class="card full scope-repo">
          <h2 data-i="heatmap">{t['heatmap']}</h2>
          <div class="hint" data-i="hint_heat">{t['hint_heat']}</div>
          <div id="chart-heat" class="chart tall"></div>
        </div>
        <div class="card full">
          <h2 data-i="recent">{t['recent']}</h2>
          <div class="table-tools">
            <div class="pager" role="navigation" aria-label="Table pages">
              <button type="button" id="btn-page-prev" data-i="page_prev">上一页</button>
              <span class="pager-meta" id="pager-meta"></span>
              <button type="button" id="btn-page-next" data-i="page_next">下一页</button>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th data-i="col_time">{t['col_time']}</th>
                  <th data-i="col_user">{t['col_user']}</th>
                  <th data-i="col_repo">{t['col_repo']}</th>
                  <th data-i="col_remote">{t['col_remote']}</th>
                  <th data-i="col_provider">{t['col_provider']}</th>
                  <th data-i="col_model">{t['col_model']}</th>
                  <th data-i="col_action">{t['col_action']}</th>
                  <th data-i="col_tokens">{t['col_tokens']}</th>
                  <th data-i="col_meta">{t['col_meta']}</th>
                  <th data-i="col_status">{t['col_status']}</th>
                </tr>
              </thead>
              <tbody id="recent-body"></tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <footer data-i="footer">{html.escape(t['footer'])}</footer>
  </div>
  <div class="toast" id="toast"></div>

<script>
const I18N_ALL = {i18n_js};
let lang = document.documentElement.getAttribute('data-lang') === 'cn' ? 'cn' : 'en';
let I18N = I18N_ALL[lang] || I18N_ALL.en;

function themeColors() {{
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? ['#0284c7', '#0f766e', '#7c3aed', '#d97706', '#db2777', '#2563eb', '#e11d48', '#0d9488']
    : ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#fb7185', '#2dd4bf'];
}}
let DATASETS = window.__GAI_USAGE_DATASETS__ || {{ all: {{}}, projects: [], by_project: {{}}, default_project: '__all__' }};
let A = DATASETS.all || {{}};
let currentProject = DATASETS.default_project || '__all__';
let currentTrend = (A && A.default_trend) || 'today';
let chartHandles = [];
let toastTimer = null;
let dropdownBound = false;

function cssVar(name, fallback) {{
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}}

function activeAnalytics() {{
  if (currentProject === '__all__') return DATASETS.all || {{}};
  return (DATASETS.by_project || {{}})[currentProject] || DATASETS.all || {{}};
}}

function pieData(series, valueKey) {{
  const labels = series.labels || [];
  const values = series[valueKey || 'tokens'] || [];
  return labels.map((name, i) => ({{ name, value: values[i] || 0 }})).filter(d => d.value > 0);
}}

function localizedStatus(name) {{
  if (name === 'ok') return I18N.ok;
  if (name === 'fail') return I18N.fail;
  if (name === 'unknown') return I18N.unknown;
  if (name === 'prompt') return I18N.prompt;
  if (name === 'completion') return I18N.completion;
  return name;
}}

function baseText() {{
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return {{
    color: cssVar('--chart-muted', '#94a3b8'),
    fontSize: 11,
    fontWeight: light ? 600 : 500
  }};
}}

function trendHints() {{
  return {{
    today: I18N.hint_today,
    last7: I18N.hint_last7,
    last15: I18N.hint_last15,
    week: I18N.hint_week,
    month: I18N.hint_month,
    year: I18N.hint_year,
    all_days: I18N.hint_all_days,
  }};
}}

function trendTitles() {{
  return {{
    today: I18N.trend_today,
    last7: I18N.trend_last7,
    last15: I18N.trend_last15,
    week: I18N.trend_week,
    month: I18N.trend_month,
    year: I18N.trend_year,
    all_days: I18N.trend_all_days,
  }};
}}

function applyTrend(chart, mode) {{
  currentTrend = mode;
  const trends = A.trends || {{}};
  const series = trends[mode] || trends.today || A.by_day || {{ labels: [], calls: [], tokens: [] }};
  const titles = trendTitles();
  const hints = trendHints();
  const titleEl = document.getElementById('trend-title');
  const hintEl = document.getElementById('trend-hint');
  if (titleEl) titleEl.textContent = titles[mode] || I18N.trend_title;
  if (hintEl) hintEl.textContent = hints[mode] || I18N.hint_day;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const tokenColor = isLight ? '#0284c7' : '#38bdf8';
  const callColor = isLight ? '#0f766e' : '#34d399';
  const symbolStroke = cssVar('--chart-symbol-stroke', '#ffffff');
  chart.setOption({{
    color: [tokenColor, callColor],
    tooltip: {{ trigger: 'axis' }},
    legend: {{
      data: [I18N.tokens, I18N.calls],
      textStyle: {{ color: cssVar('--chart-label', '#cbd5e1'), fontWeight: 600 }},
      top: 0
    }},
    grid: {{ left: 48, right: 48, top: 42, bottom: 48 }},
    xAxis: {{
      type: 'category',
      data: series.labels || [],
      boundaryGap: false,
      axisLabel: {{
        color: cssVar('--chart-muted', '#94a3b8'),
        fontSize: 11,
        fontWeight: 500,
        hideOverlap: true,
        rotate: (series.labels || []).length > 12 ? 30 : 0
      }},
      axisLine: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155'), width: 1.5 }} }},
      axisTick: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155') }} }}
    }},
    yAxis: [
      {{
        type: 'value',
        name: I18N.tokens,
        nameTextStyle: baseText(),
        axisLabel: baseText(),
        splitLine: {{ lineStyle: {{ color: cssVar('--chart-split', 'rgba(148,163,184,.12)'), type: 'dashed' }} }}
      }},
      {{
        type: 'value',
        name: I18N.calls,
        nameTextStyle: baseText(),
        axisLabel: baseText(),
        splitLine: {{ show: false }}
      }}
    ],
    series: [
      {{
        name: I18N.tokens,
        type: 'line',
        smooth: true,
        showSymbol: true,
        symbol: 'circle',
        symbolSize: 9,
        lineStyle: {{ width: 3, shadowBlur: 8, shadowColor: 'rgba(2,132,199,.28)' }},
        itemStyle: {{
          color: tokenColor,
          borderColor: symbolStroke,
          borderWidth: 2,
          shadowBlur: 6,
          shadowColor: 'rgba(2,132,199,.35)'
        }},
        areaStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: isLight ? 'rgba(2,132,199,.22)' : 'rgba(56,189,248,.35)' }},
            {{ offset: 1, color: isLight ? 'rgba(2,132,199,.02)' : 'rgba(56,189,248,.02)' }}
          ])
        }},
        data: series.tokens || []
      }},
      {{
        name: I18N.calls,
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        showSymbol: true,
        symbol: 'circle',
        symbolSize: 9,
        lineStyle: {{ width: 3, shadowBlur: 8, shadowColor: 'rgba(15,118,110,.25)' }},
        itemStyle: {{
          color: callColor,
          borderColor: symbolStroke,
          borderWidth: 2,
          shadowBlur: 6,
          shadowColor: 'rgba(15,118,110,.3)'
        }},
        data: series.calls || []
      }}
    ]
  }}, true);
}}

function initDayChart() {{
  const el = document.getElementById('chart-day');
  const chart = echarts.init(el, null, {{ renderer: 'canvas' }});
  applyTrend(chart, currentTrend || A.default_trend || 'today');
  const seg = document.getElementById('trend-seg');
  if (seg) {{
    seg.querySelectorAll('button').forEach(btn => {{
      btn.classList.toggle('active', btn.dataset.mode === currentTrend);
      btn.onclick = () => {{
        const mode = btn.dataset.mode;
        seg.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
        applyTrend(chart, mode);
      }};
    }});
  }}
  return chart;
}}

function initPie(id, series, opts) {{
  opts = opts || {{}};
  const valueKey = opts.valueKey || 'tokens';
  const unit = opts.unit || I18N.tokens;
  const colors = opts.colors || themeColors();
  const data = pieData(series, valueKey).map(d => ({{
    name: opts.localize ? localizedStatus(d.name) : d.name,
    value: d.value
  }}));
  const chart = echarts.init(document.getElementById(id));
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  chart.setOption({{
    color: colors,
    tooltip: {{
      trigger: 'item',
      formatter: function (p) {{
        return p.name + '<br/>' + p.value + ' (' + unit + ') · ' + p.percent + '%';
      }}
    }},
    legend: {{
      type: 'scroll',
      orient: 'vertical',
      right: 0,
      top: 'middle',
      textStyle: {{ color: cssVar('--chart-label', '#cbd5e1'), fontSize: 11, fontWeight: 600 }}
    }},
    series: [{{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['38%', '52%'],
      avoidLabelOverlap: true,
      itemStyle: {{
        borderRadius: 8,
        borderColor: cssVar('--chart-pie-border', '#121a2b'),
        borderWidth: isLight ? 3 : 2,
        shadowBlur: isLight ? 8 : 4,
        shadowColor: isLight ? 'rgba(16,35,63,.12)' : 'rgba(0,0,0,.35)'
      }},
      label: {{
        color: cssVar('--chart-label', '#e2e8f0'),
        fontWeight: 600,
        formatter: '{{b}}'
      }},
      labelLine: {{
        lineStyle: {{ color: cssVar('--chart-line', '#94a3b8'), width: 1.5 }}
      }},
      data
    }}]
  }});
  return chart;
}}

function initBar(id, series, opts) {{
  opts = opts || {{}};
  const valueKey = opts.valueKey || 'tokens';
  const unit = opts.unit || I18N.tokens;
  const chart = echarts.init(document.getElementById(id));
  const labels = (series.labels || []).slice();
  const values = (series[valueKey] || []).slice();
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  chart.setOption({{
    color: ['#a78bfa'],
    tooltip: {{
      trigger: 'axis',
      axisPointer: {{ type: 'shadow' }},
      formatter: function (items) {{
        const p = items[0];
        return p.name + '<br/>' + p.value + ' ' + unit;
      }}
    }},
    grid: {{ left: 16, right: 24, top: 24, bottom: 24, containLabel: true }},
    xAxis: {{
      type: 'value',
      axisLabel: baseText(),
      axisLine: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155'), width: 1.5 }} }},
      splitLine: {{ lineStyle: {{ color: cssVar('--chart-split', 'rgba(148,163,184,.12)'), type: 'dashed' }} }}
    }},
    yAxis: {{
      type: 'category',
      data: labels,
      axisLabel: {{
        color: cssVar('--chart-muted', '#94a3b8'),
        fontSize: 11,
        fontWeight: 500,
        width: 120,
        overflow: 'truncate'
      }},
      axisLine: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155'), width: 1.5 }} }}
    }},
    series: [{{
      type: 'bar',
      data: values,
      barMaxWidth: 22,
      itemStyle: {{
        borderRadius: [0, 10, 10, 0],
        borderColor: isLight ? 'rgba(255,255,255,.85)' : 'rgba(255,255,255,.12)',
        borderWidth: 1,
        shadowBlur: isLight ? 8 : 6,
        shadowColor: isLight ? 'rgba(16,35,63,.14)' : 'rgba(0,0,0,.35)',
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          {{ offset: 0, color: opts.from || (isLight ? '#0f766e' : '#6366f1') }},
          {{ offset: 1, color: opts.to || (isLight ? '#38bdf8' : '#38bdf8') }}
        ])
      }}
    }}]
  }});
  return chart;
}}

function initHeatmapGeneric(elId, yKey, yLabels, actions, raw) {{
  const chart = echarts.init(document.getElementById(elId));
  const maxVal = raw.reduce((m, d) => Math.max(m, d[2] || 0), 0) || 1;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  chart.setOption({{
    tooltip: {{
      position: 'top',
      formatter: function (p) {{
        const a = actions[p.value[0]] || '';
        const y = yLabels[p.value[1]] || '';
        return y + ' × ' + a + '<br/>' + p.value[2] + ' ' + I18N.tokens;
      }}
    }},
    grid: {{ left: 90, right: 30, top: 20, bottom: 60 }},
    xAxis: {{
      type: 'category',
      data: actions,
      splitArea: {{ show: true }},
      axisLabel: {{
        color: cssVar('--chart-muted', '#94a3b8'),
        fontSize: 11,
        fontWeight: 500,
        rotate: actions.length > 5 ? 25 : 0
      }},
      axisLine: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155'), width: 1.5 }} }}
    }},
    yAxis: {{
      type: 'category',
      data: yLabels,
      splitArea: {{ show: true }},
      axisLabel: {{
        color: cssVar('--chart-muted', '#94a3b8'),
        fontSize: 11,
        fontWeight: 500,
        width: 80,
        overflow: 'truncate'
      }},
      axisLine: {{ lineStyle: {{ color: cssVar('--chart-line', '#334155'), width: 1.5 }} }}
    }},
    visualMap: {{
      min: 0,
      max: maxVal,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      textStyle: {{ color: cssVar('--chart-muted', '#94a3b8'), fontWeight: 600 }},
      inRange: {{
        color: [
          cssVar('--heat-0', '#0f172a'),
          cssVar('--heat-1', '#1d4ed8'),
          cssVar('--heat-2', '#38bdf8'),
          cssVar('--heat-3', '#fbbf24')
        ]
      }}
    }},
    series: [{{
      name: yKey,
      type: 'heatmap',
      data: raw,
      label: {{
        show: true,
        color: isLight ? '#10233f' : '#e2e8f0',
        fontSize: 10,
        fontWeight: 600
      }},
      itemStyle: {{
        borderColor: isLight ? '#ffffff' : 'rgba(15,23,42,.55)',
        borderWidth: 2,
        shadowBlur: isLight ? 4 : 0,
        shadowColor: 'rgba(16,35,63,.12)'
      }},
      emphasis: {{
        itemStyle: {{ shadowBlur: 10, shadowColor: 'rgba(0,0,0,.45)' }}
      }}
    }}]
  }});
  return chart;
}}

function initHeatmap() {{
  const heat = A.heatmap || {{}};
  return initHeatmapGeneric(
    'chart-heat',
    'branch',
    heat.branches || [],
    heat.actions || [],
    heat.data || []
  );
}}

function initHeatmapRepo() {{
  const heat = A.heatmap_repo || {{}};
  return initHeatmapGeneric(
    'chart-heat-repo',
    'repo',
    heat.repos || [],
    heat.actions || [],
    heat.data || []
  );
}}

const TABLE_PAGE_SIZE = 25;
let tablePage = 0;

function recentRows() {{
  return A.recent || [];
}}

function fillTable() {{
  const body = document.getElementById('recent-body');
  body.innerHTML = '';
  const rows = recentRows();
  const pages = Math.max(1, Math.ceil(rows.length / TABLE_PAGE_SIZE) || 1);
  if (tablePage >= pages) tablePage = pages - 1;
  if (tablePage < 0) tablePage = 0;
  const start = tablePage * TABLE_PAGE_SIZE;
  const slice = rows.slice(start, start + TABLE_PAGE_SIZE);
  for (const r of slice) {{
    const tr = document.createElement('tr');
    const who = r.git_user && r.git_email
      ? `${{r.git_user}} <${{r.git_email}}>`
      : (r.git_user || r.git_email || '—');
    const repo = r.repo_name || '—';
    const remote = (r.remote_name === null || r.remote_name === undefined)
      ? 'null'
      : (r.remote_name || '—');
    const action = r.action_detail || r.action || '—';
    const tokens = r.total_tokens != null ? r.total_tokens : '—';
    const meta = [
      r.branch,
      r.files_count != null ? `${{r.files_count}} files` : '',
      r.diff_chars != null ? `${{r.diff_chars}} chars` : '',
      r.commit_count != null ? `${{r.commit_count}} commits` : '',
      r.since ? `since=${{r.since}}` : '',
      r.duration_ms != null ? `${{r.duration_ms}}ms` : '',
    ].filter(Boolean).join(' · ') || '—';
    const status = r.ok === false
      ? `<span class="pill fail">FAIL${{r.error_kind ? ' · ' + r.error_kind : ''}}</span>`
      : (r.ok === true ? `<span class="pill ok">OK</span>` : '—');
    tr.innerHTML = `
      <td>${{esc(r.ts || '')}}</td>
      <td>${{esc(who)}}</td>
      <td>${{esc(repo)}}</td>
      <td>${{esc(remote)}}</td>
      <td>${{esc(r.provider_name || r.provider || '')}}</td>
      <td>${{esc(r.model || '')}}</td>
      <td>${{esc(action)}}</td>
      <td>${{esc(String(tokens))}}</td>
      <td>${{esc(meta)}}</td>
      <td>${{status}}</td>`;
    body.appendChild(tr);
  }}
  const metaEl = document.getElementById('pager-meta');
  const prev = document.getElementById('btn-page-prev');
  const next = document.getElementById('btn-page-next');
  if (metaEl) {{
    const shown = rows.length
      ? `${{start + 1}}–${{start + slice.length}} / ${{rows.length}}`
      : '0 / 0';
    metaEl.textContent = (I18N.page_of || 'Page {{page}}/{{pages}} · {{shown}}')
      .replace('{{page}}', String(tablePage + 1))
      .replace('{{pages}}', String(pages))
      .replace('{{shown}}', shown);
  }}
  if (prev) prev.disabled = tablePage <= 0;
  if (next) next.disabled = tablePage >= pages - 1 || rows.length === 0;
}}

function exportCsv() {{
  const rows = recentRows();
  const headers = [
    'ts','git_user','git_email','repo_name','remote_name','provider','model',
    'action','action_detail','total_tokens','prompt_tokens','completion_tokens',
    'branch','ok','error_kind','duration_ms'
  ];
  const escapeCell = (v) => {{
    const s = v == null ? '' : String(v);
    if (/[",\\n\\r]/.test(s)) return '"' + s.replaceAll('"', '""') + '"';
    return s;
  }};
  const lines = [headers.join(',')];
  for (const r of rows) {{
    lines.push(headers.map((h) => escapeCell(r[h])).join(','));
  }}
  const blob = new Blob([lines.join('\\n')], {{ type: 'text/csv;charset=utf-8' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'gai-usage.csv';
  a.click();
  URL.revokeObjectURL(a.href);
  showToast(I18N.export_ok || 'CSV exported');
}}

function esc(s) {{
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}}

function updateKpis() {{
  const totals = A.totals || {{}};
  const setText = (id, value) => {{
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }};
  setText('kpi-calls', totals.calls || 0);
  setText('kpi-tokens', totals.tokens || 0);
  setText('kpi-ok', totals.ok || 0);
  setText('kpi-fail', totals.fail || 0);
  setText(
    'kpi-ms',
    totals.avg_duration_ms == null ? '—' : (totals.avg_duration_ms + ' ms')
  );
  setText(
    'kpi-token-sub',
    I18N.prompt + ': ' + (totals.prompt_tokens || 0) +
    ' · ' + I18N.completion + ': ' + (totals.completion_tokens || 0)
  );
}}

function disposeCharts() {{
  chartHandles.forEach(c => {{ try {{ c.dispose(); }} catch (e) {{}} }});
  chartHandles = [];
}}

function applyViewScope() {{
  const isAll = currentProject === '__all__';
  document.documentElement.classList.toggle('view-all', isAll);
  document.documentElement.classList.toggle('view-repo', !isAll);
  const hint = document.getElementById('project-hint');
  if (hint) {{
    hint.textContent = isAll ? I18N.hint_project_all : I18N.hint_project_repo;
  }}
}}

function renderDashboard() {{
  A = activeAnalytics();
  applyViewScope();
  updateKpis();
  const totals = A.totals || {{}};
  const empty = (totals.calls || 0) === 0;
  document.getElementById('empty').style.display = empty ? 'block' : 'none';
  document.getElementById('content').style.display = empty ? 'none' : 'block';
  disposeCharts();
  if (empty) return;

  const isAll = currentProject === '__all__';
  const charts = [
    initDayChart(),
    initPie('chart-status', A.by_status || {{}}, {{
      valueKey: 'calls',
      unit: I18N.calls,
      localize: true,
      colors: ['#34d399', '#f87171', '#94a3b8']
    }}),
    initPie('chart-split', A.token_split || {{}}, {{
      localize: true,
      colors: ['#38bdf8', '#a78bfa']
    }}),
    initBar('chart-duration', A.duration_by_model || {{}}, {{
      valueKey: 'avg_ms',
      unit: 'ms',
      from: '#f59e0b',
      to: '#fbbf24'
    }}),
    initPie('chart-action', A.by_action || {{}}),
    initPie('chart-provider', A.by_provider || {{}}),
    initBar('chart-model', A.by_model || {{}}),
    initBar('chart-user', A.by_user || {{}}, {{ from: '#10b981', to: '#34d399' }}),
  ];
  if (isAll) {{
    charts.push(
      initBar('chart-repo', A.by_repo || {{}}, {{ from: '#22d3ee', to: '#38bdf8' }}),
      initHeatmapRepo()
    );
  }} else {{
    charts.push(
      initBar('chart-branch', A.by_branch || {{}}, {{ from: '#0ea5e9', to: '#22d3ee' }}),
      initHeatmap()
    );
  }}
  chartHandles = charts;
  fillTable();
}}

function showToast(msg) {{
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 1600);
}}

function updateMetaLine() {{
  const el = document.getElementById('meta-line');
  if (!el) return;
  const a = DATASETS.all || {{}};
  el.innerHTML =
    I18N.generated + ': ' + esc(String(a.generated_at || '—')) +
    '<br/>' + I18N.source + ': ' + esc(String(a.source || 'usage.jsonl'));
}}

function applyStaticI18n() {{
  document.querySelectorAll('[data-i]').forEach((el) => {{
    const key = el.getAttribute('data-i');
    if (key && typeof I18N[key] === 'string') el.textContent = I18N[key];
  }});
  document.title = I18N.title || document.title;
  const refresh = document.getElementById('btn-refresh');
  if (refresh && !refresh.disabled) refresh.textContent = I18N.refresh;
  updateMetaLine();
}}

function rebuildProjectMenu() {{
  const menu = document.getElementById('project-dd-menu');
  if (!menu) return;
  const ids = new Set((DATASETS.projects || []).map((p) => p.id));
  if (currentProject !== '__all__' && !ids.has(currentProject)) {{
    currentProject = DATASETS.default_project || '__all__';
  }}
  const items = [{{ id: '__all__', label: I18N.project_all }}].concat(DATASETS.projects || []);
  menu.innerHTML = '';
  items.forEach((item) => {{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dd-item' + (item.id === currentProject ? ' active' : '');
    btn.dataset.value = item.id;
    btn.setAttribute('role', 'option');
    const mark = document.createElement('span');
    mark.className = 'dd-dot ' + (item.id === '__all__' ? 'all' : 'repo');
    const text = document.createElement('span');
    text.className = 'dd-item-text';
    text.textContent = item.label || item.id;
    const check = document.createElement('span');
    check.className = 'dd-check';
    check.textContent = '✓';
    btn.appendChild(mark);
    btn.appendChild(text);
    btn.appendChild(check);
    btn.addEventListener('click', (e) => {{
      e.stopPropagation();
      currentProject = item.id || '__all__';
      tablePage = 0;
      syncProjectDropdown();
      const root = document.getElementById('project-dd');
      const trigger = document.getElementById('project-dd-btn');
      if (root) root.classList.remove('open');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      renderDashboard();
    }});
    menu.appendChild(btn);
  }});
  syncProjectDropdown();
}}

function syncProjectDropdown() {{
  const labelEl = document.getElementById('project-dd-label');
  const menu = document.getElementById('project-dd-menu');
  if (!menu) return;
  let activeLabel = I18N.project_all;
  menu.querySelectorAll('.dd-item').forEach(btn => {{
    const on = btn.dataset.value === currentProject;
    btn.classList.toggle('active', on);
    if (on) {{
      const text = btn.querySelector('.dd-item-text');
      activeLabel = text ? text.textContent : btn.dataset.value;
    }}
  }});
  if (labelEl) labelEl.textContent = activeLabel || I18N.project_all;
}}

function initProjectDropdown() {{
  const root = document.getElementById('project-dd');
  const btn = document.getElementById('project-dd-btn');
  const menu = document.getElementById('project-dd-menu');
  if (!root || !btn || !menu || dropdownBound) {{
    rebuildProjectMenu();
    return;
  }}
  dropdownBound = true;

  const close = () => {{
    root.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
  }};
  const open = () => {{
    root.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
  }};

  btn.addEventListener('click', (e) => {{
    e.stopPropagation();
    if (root.classList.contains('open')) close();
    else open();
  }});
  document.addEventListener('click', (e) => {{
    if (!root.contains(e.target)) close();
  }});
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape') close();
  }});
  rebuildProjectMenu();
}}

function applyDatasets(next) {{
  DATASETS = next || window.__GAI_USAGE_DATASETS__ || DATASETS;
  window.__GAI_USAGE_DATASETS__ = DATASETS;
  A = DATASETS.all || {{}};
  if (!currentTrend) currentTrend = A.default_trend || 'today';
  tablePage = 0;
  rebuildProjectMenu();
  updateMetaLine();
  renderDashboard();
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
  const old = document.getElementById('usage-data-loader');
  if (old) old.remove();
  const s = document.createElement('script');
  s.id = 'usage-data-loader';
  s.src = 'usage-data.js?t=' + Date.now();
  s.onload = () => {{
    applyDatasets(window.__GAI_USAGE_DATASETS__);
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

(function main() {{
  document.getElementById('btn-refresh').addEventListener('click', refreshData);
  document.getElementById('btn-export-csv').addEventListener('click', exportCsv);
  document.getElementById('btn-page-prev').addEventListener('click', () => {{
    tablePage -= 1;
    fillTable();
  }});
  document.getElementById('btn-page-next').addEventListener('click', () => {{
    tablePage += 1;
    fillTable();
  }});
  document.getElementById('btn-theme-light').addEventListener('click', () => setTheme('light'));
  document.getElementById('btn-theme-dark').addEventListener('click', () => setTheme('dark'));
  document.getElementById('btn-lang-cn').addEventListener('click', () => setLang('cn'));
  document.getElementById('btn-lang-en').addEventListener('click', () => setLang('en'));
  setTheme(currentTheme(), false);
  setLang(lang);
  initProjectDropdown();
  applyDatasets(window.__GAI_USAGE_DATASETS__);
  window.addEventListener('resize', () => chartHandles.forEach(c => c.resize()));
  requestAnimationFrame(() => document.documentElement.classList.add('theme-ready'));
}})();
</script>
</body>
</html>
"""


def _series(bucket: dict[str, dict[str, int]]) -> dict[str, list[Any]]:
    items = sorted(bucket.items(), key=lambda kv: (-kv[1]["tokens"], -kv[1]["calls"], kv[0]))
    return {
        "labels": [k for k, _ in items],
        "calls": [v["calls"] for _, v in items],
        "tokens": [v["tokens"] for _, v in items],
    }


def _duration_series(bucket: dict[str, list[int]]) -> dict[str, list[Any]]:
    items = []
    for model, vals in bucket.items():
        if not vals:
            continue
        items.append((model, int(sum(vals) / len(vals)), len(vals)))
    items.sort(key=lambda x: (-x[1], x[0]))
    return {
        "labels": [m for m, _, _ in items],
        "avg_ms": [avg for _, avg, _ in items],
        "calls": [n for _, _, n in items],
    }


def _day_key(ts: str) -> str:
    dt = _parse_ts_dt(ts)
    if dt is None:
        text = (ts or "").strip()
        return text[:10] if len(text) >= 10 else "unknown"
    return dt.date().isoformat()


def _parse_ts_dt(ts: str) -> datetime | None:
    text = (ts or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _rolling_day_series(
    parsed: list[tuple[datetime, int]],
    *,
    today: date,
    days: int,
) -> dict[str, list[Any]]:
    labels = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    index = {label: i for i, label in enumerate(labels)}
    tokens = [0] * len(labels)
    calls = [0] * len(labels)
    for dt, tok in parsed:
        key = dt.date().isoformat()
        idx = index.get(key)
        if idx is None:
            continue
        calls[idx] += 1
        tokens[idx] += tok
    return {"labels": labels, "calls": calls, "tokens": tokens}


def _all_day_keys(parsed: list[tuple[datetime, int]]) -> list[str]:
    if not parsed:
        return []
    days = sorted({dt.date() for dt, _ in parsed})
    start, end = days[0], days[-1]
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _bucket_series(
    parsed: list[tuple[datetime, int]],
    *,
    key_fn,
    fill_keys: list[str] | None = None,
) -> dict[str, list[Any]]:
    tokens_map: dict[str, int] = defaultdict(int)
    calls_map: dict[str, int] = defaultdict(int)
    for dt, tok in parsed:
        key = key_fn(dt)
        calls_map[key] += 1
        tokens_map[key] += tok
    if fill_keys is None:
        labels = sorted(calls_map.keys())
    else:
        labels = list(fill_keys)
        for key in calls_map:
            if key not in labels:
                labels.append(key)
        # keep chronological where possible
        labels = sorted(set(labels))
    return {
        "labels": labels,
        "calls": [calls_map.get(k, 0) for k in labels],
        "tokens": [tokens_map.get(k, 0) for k in labels],
    }


def _i18n(chinese: bool) -> dict[str, str]:
    if chinese:
        return {
            "title": "gai Token 用量报告",
            "generated": "生成时间",
            "source": "数据源",
            "empty": "暂无用量数据。请先使用 gai review / commit / report 产生调用，再重新生成报告。",
            "calls": "调用次数",
            "tokens": "Token 合计",
            "prompt": "输入",
            "completion": "输出",
            "ok": "成功",
            "fail": "失败",
            "unknown": "未知",
            "avg_ms": "平均耗时",
            "trend_title": "用量趋势",
            "trend_today": "今日趋势（0 点 → 当前）",
            "trend_last7": "最近 7 天",
            "trend_last15": "最近 15 天",
            "trend_week": "按周汇总",
            "trend_month": "按月汇总",
            "trend_year": "按年汇总",
            "trend_all_days": "全部按日",
            "seg_today": "今日",
            "seg_last7": "近7天",
            "seg_last15": "近15天",
            "seg_week": "按周",
            "seg_month": "按月",
            "seg_year": "按年",
            "seg_all_days": "全部日",
            "project_filter": "项目仓库",
            "project_all": "全部项目",
            "hint_project": "按仓库筛选；远程与仓库绑定，不做单独筛选",
            "hint_project_all": "总览：跨仓库对比（按仓库用量、仓库×动作）",
            "hint_project_repo": "单仓详情：分支分布、动作×分支等仓内分析",
            "by_day": "用量趋势",
            "by_repo": "按仓库用量",
            "hint_repo": "全部项目总览：对比各仓库 Token 消耗",
            "heatmap_repo": "仓库 × 动作（Token 热力图）",
            "hint_heat_repo": "全部项目总览：颜色越亮表示该仓库上该动作消耗越多",
            "by_branch": "按分支用量",
            "hint_branch_repo": "单仓详情：当前仓库内各分支 Token 消耗",
            "by_status": "成功 / 失败",
            "token_split": "输入 vs 输出 Token",
            "duration_by_model": "按模型平均耗时",
            "by_action": "按动作分布",
            "by_provider": "按厂商分布",
            "by_model": "按模型用量",
            "by_user": "按用户用量",
            "heatmap": "动作 × 分支（Token 热力图）",
            "hint_heat": "单仓详情：颜色越亮表示该分支上该动作消耗越多",
            "hint_day": "双轴：Token 与调用次数",
            "hint_today": "当天 0:00 到当前时刻，按小时统计",
            "hint_last7": "含今天在内的最近 7 个自然日",
            "hint_last15": "含今天在内的最近 15 个自然日",
            "hint_week": "按 ISO 周聚合（如 2026-W41）",
            "hint_month": "按自然月聚合（YYYY-MM）",
            "hint_year": "按自然年聚合（YYYY）",
            "hint_all_days": "历史全部日期（按天）",
            "hint_pie": "环形图按 Token 占比",
            "hint_bar": "横向柱状图按 Token",
            "hint_status": "按调用次数看稳定性",
            "hint_split": "区分读入与生成消耗",
            "hint_duration": "单位：毫秒（ms）",
            "recent": "最近记录（最多 100 条）",
            "col_time": "时间",
            "col_user": "用户",
            "col_repo": "仓库",
            "col_remote": "远程",
            "col_provider": "厂商",
            "col_model": "模型",
            "col_action": "动作",
            "col_tokens": "Token",
            "col_meta": "上下文",
            "col_status": "状态",
            "refresh": "刷新",
            "refreshing": "刷新中…",
            "refresh_ok": "已更新到最新用量数据",
            "refresh_fail": "刷新失败：找不到 usage-data.js",
            "refresh_fail_file": "刷新失败：file:// 下可能被浏览器拦截。请改用 gai usage --report --serve，或确认同目录有 usage-data.js",
            "refresh_fail_http": "刷新失败：找不到 usage-data.js。请先执行 gai usage --report，或再跑一次会产生用量的 gai 命令",
            "export_csv": "导出 CSV",
            "export_ok": "已导出 CSV",
            "page_prev": "上一页",
            "page_next": "下一页",
            "page_of": "第 {{page}}/{{pages}} 页 · {{shown}}",
            "theme_light": "日间",
            "theme_dark": "夜间",
            "footer": "数据来自 .gai/usage.jsonl（同步为 usage-data.js）。点「刷新」可加载最新数据；日常 gai 调用也会自动更新数据文件。file:// 刷新不稳时用 gai usage --report --serve。",
        }
    return {
        "title": "gai Token Usage Report",
        "generated": "Generated",
        "source": "Source",
        "empty": "No usage data yet. Run gai review / commit / report, then regenerate this report.",
        "calls": "Calls",
        "tokens": "Tokens",
        "prompt": "Prompt",
        "completion": "Completion",
        "ok": "OK",
        "fail": "Failed",
        "unknown": "Unknown",
        "avg_ms": "Avg duration",
        "trend_title": "Usage trend",
        "trend_today": "Today (00:00 → now)",
        "trend_last7": "Last 7 days",
        "trend_last15": "Last 15 days",
        "trend_week": "By week",
        "trend_month": "By month",
        "trend_year": "By year",
        "trend_all_days": "All days",
        "seg_today": "Today",
        "seg_last7": "7d",
        "seg_last15": "15d",
        "seg_week": "Week",
        "seg_month": "Month",
        "seg_year": "Year",
        "seg_all_days": "All days",
        "project_filter": "Project repo",
        "project_all": "All projects",
        "hint_project": "Filter by repo; remote is bound to repo (not a separate filter)",
        "hint_project_all": "Overview: compare across repos (by repo, repo×action)",
        "hint_project_repo": "Repo detail: branch breakdown, action×branch, etc.",
        "by_day": "Usage trend",
        "by_repo": "By repository",
        "hint_repo": "All-projects overview: compare token usage by repo",
        "heatmap_repo": "Repo × action heatmap (tokens)",
        "hint_heat_repo": "All-projects overview: brighter means more tokens for that action in that repo",
        "by_branch": "By branch",
        "hint_branch_repo": "Repo detail: token usage by branch in the selected repo",
        "by_status": "Success / failure",
        "token_split": "Prompt vs completion tokens",
        "duration_by_model": "Avg duration by model",
        "by_action": "By action",
        "by_provider": "By provider",
        "by_model": "By model",
        "by_user": "By user",
        "heatmap": "Action × branch heatmap (tokens)",
        "hint_heat": "Repo detail: brighter means more tokens for that action on that branch",
        "hint_day": "Dual axis: tokens and call count",
        "hint_today": "Today from 00:00 to now, hourly buckets",
        "hint_last7": "Last 7 calendar days including today",
        "hint_last15": "Last 15 calendar days including today",
        "hint_week": "Aggregated by ISO week (e.g. 2026-W41)",
        "hint_month": "Aggregated by calendar month (YYYY-MM)",
        "hint_year": "Aggregated by calendar year (YYYY)",
        "hint_all_days": "All historical days",
        "hint_pie": "Donut chart by token share",
        "hint_bar": "Horizontal bars by tokens",
        "hint_status": "Call counts for reliability",
        "hint_split": "Separate read vs generate cost",
        "hint_duration": "Unit: milliseconds (ms)",
        "recent": "Recent records (up to 100)",
        "col_time": "Time",
        "col_user": "User",
        "col_repo": "Repo",
        "col_remote": "Remote",
        "col_provider": "Provider",
        "col_model": "Model",
        "col_action": "Action",
        "col_tokens": "Tokens",
        "col_meta": "Context",
        "col_status": "Status",
        "refresh": "Refresh",
        "refreshing": "Refreshing…",
        "refresh_ok": "Usage data updated",
        "refresh_fail": "Refresh failed: usage-data.js missing",
        "refresh_fail_file": "Refresh failed: browsers may block file:// script reloads. Use gai usage --report --serve, or ensure usage-data.js sits beside this HTML.",
        "refresh_fail_http": "Refresh failed: usage-data.js missing. Run gai usage --report, or any gai command that records LLM usage.",
        "export_csv": "Export CSV",
        "export_ok": "CSV exported",
        "page_prev": "Prev",
        "page_next": "Next",
        "page_of": "Page {{page}}/{{pages}} · {{shown}}",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "footer": "Data from .gai/usage.jsonl (synced to usage-data.js). Click Refresh for the latest snapshot; normal gai LLM calls also update the data file. Prefer gai usage --report --serve if file:// refresh is blocked.",
    }
