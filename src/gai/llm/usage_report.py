"""Build a fixed project HTML dashboard from usage.jsonl (ECharts)."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from gai.llm.history import UsageRecord, project_root, summarize_records, usage_log_path

_REPORT_RELATIVE = Path(".gai") / "usage-report.html"


def usage_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _REPORT_RELATIVE


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
    target.write_text(
        render_usage_report_html(datasets, chinese=chinese),
        encoding="utf-8",
    )
    return target


def render_usage_report_html(datasets: dict[str, Any], *, chinese: bool = False) -> str:
    """Self-contained HTML dashboard powered by ECharts (CDN)."""
    t = _i18n(chinese)
    analytics = datasets.get("all") or {}
    payload = json.dumps(datasets, ensure_ascii=False)
    payload_js = json.dumps(payload)
    i18n_js = json.dumps(t, ensure_ascii=False)
    title = html.escape(t["title"])
    generated = html.escape(str(analytics.get("generated_at") or ""))
    source = html.escape(str(analytics.get("source") or ""))
    totals = analytics.get("totals") or {}
    calls = totals.get("calls", 0)
    tokens = totals.get("tokens", 0)
    ok = totals.get("ok", 0)
    fail = totals.get("fail", 0)
    avg_ms = totals.get("avg_duration_ms")
    avg_display = "—" if avg_ms is None else f"{avg_ms} ms"
    prompt = totals.get("prompt_tokens", 0)
    completion = totals.get("completion_tokens", 0)
    project_options = ['<option value="__all__">' + html.escape(t["project_all"]) + "</option>"]
    for item in datasets.get("projects") or []:
        pid = html.escape(str(item.get("id") or ""))
        label = html.escape(str(item.get("label") or pid))
        project_options.append(f'<option value="{pid}">{label}</option>')
    project_options_html = "\n".join(project_options)

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if chinese else 'en'}" class="view-all">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
<style>
  :root {{
    --bg0: #0b1220;
    --bg1: #121a2b;
    --panel: rgba(22, 32, 51, 0.92);
    --panel-border: rgba(148, 163, 184, 0.14);
    --text: #e8eef8;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent2: #a78bfa;
    --ok: #34d399;
    --fail: #f87171;
    --warn: #fbbf24;
    --shadow: 0 18px 50px rgba(0,0,0,.35);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    color: var(--text);
    font-family: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background:
      radial-gradient(900px 420px at 8% -8%, rgba(56,189,248,.18), transparent 55%),
      radial-gradient(800px 380px at 92% 0%, rgba(167,139,250,.16), transparent 50%),
      linear-gradient(180deg, var(--bg1), var(--bg0));
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
    border-radius: 999px;
    border: 1px solid rgba(56,189,248,.35);
    background: rgba(56,189,248,.08);
    color: #bae6fd;
    font-size: .82rem;
    white-space: nowrap;
  }}
  .kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }}
  .kpi {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    padding: 16px 16px 14px;
    box-shadow: var(--shadow);
    backdrop-filter: blur(8px);
  }}
  .kpi .label {{
    color: var(--muted);
    font-size: .78rem;
  }}
  .kpi .value {{
    margin-top: 8px;
    font-size: 1.45rem;
    font-weight: 740;
    letter-spacing: -.02em;
  }}
  .kpi .sub {{
    margin-top: 4px;
    color: var(--muted);
    font-size: .75rem;
  }}
  .value.ok {{ color: var(--ok); }}
  .value.fail {{ color: var(--fail); }}
  .grid {{
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 14px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 18px;
    padding: 16px 16px 10px;
    box-shadow: var(--shadow);
    min-width: 0;
  }}
  .card.full {{ grid-column: 1 / -1; }}
  .card h2 {{
    margin: 0 0 4px;
    font-size: .98rem;
    font-weight: 650;
  }}
  .card .hint {{
    color: var(--muted);
    font-size: .78rem;
    margin-bottom: 6px;
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
    border: 1px solid rgba(148,163,184,.22);
    background: rgba(15, 23, 42, .55);
    color: #cbd5e1;
    border-radius: 999px;
    padding: 5px 10px;
    font-size: .75rem;
    cursor: pointer;
  }}
  .seg button:hover {{ border-color: rgba(56,189,248,.45); color: #e0f2fe; }}
  .seg button.active {{
    background: rgba(56,189,248,.16);
    border-color: rgba(56,189,248,.55);
    color: #bae6fd;
    font-weight: 650;
  }}
  .filters {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    margin: 0 0 16px;
    padding: 12px 14px;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
  }}
  .filters label {{
    color: var(--muted);
    font-size: .82rem;
  }}
  .filters select {{
    min-width: 220px;
    border-radius: 10px;
    border: 1px solid rgba(148,163,184,.28);
    background: rgba(15, 23, 42, .7);
    color: var(--text);
    padding: 8px 10px;
    font-size: .86rem;
  }}
  /* all = overview across repos; repo = single-repo detail */
  html.view-all .scope-repo,
  html.view-repo .scope-all {{
    display: none !important;
  }}
  .chart {{
    width: 100%;
    height: 300px;
  }}
  .chart.tall {{ height: 340px; }}
  .table-wrap {{ overflow-x: auto; margin-top: 6px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: .82rem;
  }}
  th, td {{
    text-align: left;
    padding: 10px 8px;
    border-bottom: 1px solid rgba(148,163,184,.12);
    vertical-align: top;
  }}
  th {{
    color: var(--muted);
    font-weight: 600;
    position: sticky;
    top: 0;
    background: rgba(18, 26, 43, .95);
  }}
  tr:hover td {{ background: rgba(56,189,248,.05); }}
  .pill {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: .72rem;
    font-weight: 650;
  }}
  .pill.ok {{ background: rgba(52,211,153,.15); color: var(--ok); }}
  .pill.fail {{ background: rgba(248,113,113,.15); color: var(--fail); }}
  .empty {{
    display: none;
    padding: 64px 20px;
    text-align: center;
    color: var(--muted);
    background: var(--panel);
    border: 1px dashed var(--panel-border);
    border-radius: 18px;
  }}
  footer {{
    margin-top: 22px;
    color: var(--muted);
    font-size: .78rem;
  }}
  @media (max-width: 920px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .chart, .chart.tall {{ height: 280px; }}
  }}
</style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <div class="brand">GAI USAGE</div>
        <h1>{title}</h1>
        <div class="meta">{t['generated']}: {generated}<br/>{t['source']}: {source}</div>
      </div>
      <div class="badge">ECharts · .gai/usage-report.html</div>
    </header>

    <div class="filters">
      <label for="project-filter">{t['project_filter']}</label>
      <select id="project-filter">
        {project_options_html}
      </select>
      <span class="meta" id="project-hint">{html.escape(t['hint_project'])}</span>
    </div>

    <div class="empty" id="empty">{html.escape(t['empty'])}</div>

    <div id="content">
      <section class="kpis">
        <div class="kpi">
          <div class="label">{t['calls']}</div>
          <div class="value" id="kpi-calls">{calls}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['tokens']}</div>
          <div class="value" id="kpi-tokens">{tokens}</div>
          <div class="sub" id="kpi-token-sub">{t['prompt']}: {prompt} · {t['completion']}: {completion}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['ok']}</div>
          <div class="value ok" id="kpi-ok">{ok}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['fail']}</div>
          <div class="value fail" id="kpi-fail">{fail}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['avg_ms']}</div>
          <div class="value" id="kpi-ms">{avg_display}</div>
        </div>
      </section>

      <section class="grid">
        <div class="card full">
          <div class="card-head">
            <div>
              <h2 id="trend-title">{t['trend_title']}</h2>
              <div class="hint" id="trend-hint">{t['hint_today']}</div>
            </div>
            <div class="seg" id="trend-seg" role="tablist">
              <button type="button" data-mode="today" class="active">{t['seg_today']}</button>
              <button type="button" data-mode="last7">{t['seg_last7']}</button>
              <button type="button" data-mode="last15">{t['seg_last15']}</button>
              <button type="button" data-mode="week">{t['seg_week']}</button>
              <button type="button" data-mode="month">{t['seg_month']}</button>
              <button type="button" data-mode="year">{t['seg_year']}</button>
              <button type="button" data-mode="all_days">{t['seg_all_days']}</button>
            </div>
          </div>
          <div id="chart-day" class="chart tall"></div>
        </div>
        <div class="card scope-all">
          <h2>{t['by_repo']}</h2>
          <div class="hint">{t['hint_repo']}</div>
          <div id="chart-repo" class="chart"></div>
        </div>
        <div class="card scope-repo">
          <h2>{t['by_branch']}</h2>
          <div class="hint">{t['hint_branch_repo']}</div>
          <div id="chart-branch" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['by_status']}</h2>
          <div class="hint">{t['hint_status']}</div>
          <div id="chart-status" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['token_split']}</h2>
          <div class="hint">{t['hint_split']}</div>
          <div id="chart-split" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['duration_by_model']}</h2>
          <div class="hint">{t['hint_duration']}</div>
          <div id="chart-duration" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['by_action']}</h2>
          <div class="hint">{t['hint_pie']}</div>
          <div id="chart-action" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['by_provider']}</h2>
          <div class="hint">{t['hint_pie']}</div>
          <div id="chart-provider" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['by_model']}</h2>
          <div class="hint">{t['hint_bar']}</div>
          <div id="chart-model" class="chart"></div>
        </div>
        <div class="card">
          <h2>{t['by_user']}</h2>
          <div class="hint">{t['hint_bar']}</div>
          <div id="chart-user" class="chart"></div>
        </div>
        <div class="card full scope-all">
          <h2>{t['heatmap_repo']}</h2>
          <div class="hint">{t['hint_heat_repo']}</div>
          <div id="chart-heat-repo" class="chart tall"></div>
        </div>
        <div class="card full scope-repo">
          <h2>{t['heatmap']}</h2>
          <div class="hint">{t['hint_heat']}</div>
          <div id="chart-heat" class="chart tall"></div>
        </div>
        <div class="card full">
          <h2>{t['recent']}</h2>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t['col_time']}</th>
                  <th>{t['col_user']}</th>
                  <th>{t['col_repo']}</th>
                  <th>{t['col_remote']}</th>
                  <th>{t['col_provider']}</th>
                  <th>{t['col_model']}</th>
                  <th>{t['col_action']}</th>
                  <th>{t['col_tokens']}</th>
                  <th>{t['col_meta']}</th>
                  <th>{t['col_status']}</th>
                </tr>
              </thead>
              <tbody id="recent-body"></tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <footer>{html.escape(t['footer'])}</footer>
  </div>

<script>
const DATASETS = JSON.parse({payload_js});
const I18N = {i18n_js};
const COLORS = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#fb7185', '#2dd4bf'];
let A = DATASETS.all || {{}};
let currentProject = DATASETS.default_project || '__all__';
let currentTrend = (A && A.default_trend) || 'today';
let chartHandles = [];

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
  return {{ color: '#94a3b8', fontSize: 11 }};
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
  chart.setOption({{
    color: ['#38bdf8', '#34d399'],
    tooltip: {{ trigger: 'axis' }},
    legend: {{
      data: [I18N.tokens, I18N.calls],
      textStyle: {{ color: '#cbd5e1' }},
      top: 0
    }},
    grid: {{ left: 48, right: 48, top: 42, bottom: 48 }},
    xAxis: {{
      type: 'category',
      data: series.labels || [],
      boundaryGap: false,
      axisLabel: {{
        color: '#94a3b8',
        fontSize: 11,
        hideOverlap: true,
        rotate: (series.labels || []).length > 12 ? 30 : 0
      }},
      axisLine: {{ lineStyle: {{ color: '#334155' }} }}
    }},
    yAxis: [
      {{
        type: 'value',
        name: I18N.tokens,
        nameTextStyle: baseText(),
        axisLabel: baseText(),
        splitLine: {{ lineStyle: {{ color: 'rgba(148,163,184,.12)' }} }}
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
        showSymbol: (series.labels || []).length <= 24,
        symbol: 'circle',
        symbolSize: 7,
        areaStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: 'rgba(56,189,248,.35)' }},
            {{ offset: 1, color: 'rgba(56,189,248,.02)' }}
          ])
        }},
        data: series.tokens || []
      }},
      {{
        name: I18N.calls,
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        showSymbol: (series.labels || []).length <= 24,
        symbol: 'circle',
        symbolSize: 7,
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
  const colors = opts.colors || COLORS;
  const data = pieData(series, valueKey).map(d => ({{
    name: opts.localize ? localizedStatus(d.name) : d.name,
    value: d.value
  }}));
  const chart = echarts.init(document.getElementById(id));
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
      textStyle: {{ color: '#cbd5e1', fontSize: 11 }}
    }},
    series: [{{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['38%', '52%'],
      avoidLabelOverlap: true,
      itemStyle: {{
        borderRadius: 8,
        borderColor: '#121a2b',
        borderWidth: 2
      }},
      label: {{ color: '#e2e8f0', formatter: '{{b}}' }},
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
      splitLine: {{ lineStyle: {{ color: 'rgba(148,163,184,.12)' }} }}
    }},
    yAxis: {{
      type: 'category',
      data: labels,
      axisLabel: {{ color: '#94a3b8', fontSize: 11, width: 120, overflow: 'truncate' }},
      axisLine: {{ lineStyle: {{ color: '#334155' }} }}
    }},
    series: [{{
      type: 'bar',
      data: values,
      barMaxWidth: 22,
      itemStyle: {{
        borderRadius: [0, 8, 8, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          {{ offset: 0, color: opts.from || '#6366f1' }},
          {{ offset: 1, color: opts.to || '#38bdf8' }}
        ])
      }}
    }}]
  }});
  return chart;
}}

function initHeatmapGeneric(elId, yKey, yLabels, actions, raw) {{
  const chart = echarts.init(document.getElementById(elId));
  const maxVal = raw.reduce((m, d) => Math.max(m, d[2] || 0), 0) || 1;
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
      axisLabel: {{ color: '#94a3b8', fontSize: 11, rotate: actions.length > 5 ? 25 : 0 }}
    }},
    yAxis: {{
      type: 'category',
      data: yLabels,
      splitArea: {{ show: true }},
      axisLabel: {{ color: '#94a3b8', fontSize: 11, width: 80, overflow: 'truncate' }}
    }},
    visualMap: {{
      min: 0,
      max: maxVal,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      textStyle: {{ color: '#94a3b8' }},
      inRange: {{ color: ['#0f172a', '#1d4ed8', '#38bdf8', '#fbbf24'] }}
    }},
    series: [{{
      name: yKey,
      type: 'heatmap',
      data: raw,
      label: {{ show: true, color: '#e2e8f0', fontSize: 10 }},
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

function fillTable() {{
  const body = document.getElementById('recent-body');
  body.innerHTML = '';
  for (const r of (A.recent || [])) {{
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

(function main() {{
  const filter = document.getElementById('project-filter');
  if (filter) {{
    filter.value = currentProject;
    filter.addEventListener('change', () => {{
      currentProject = filter.value || '__all__';
      renderDashboard();
    }});
  }}
  renderDashboard();
  window.addEventListener('resize', () => chartHandles.forEach(c => c.resize()));
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
            "footer": "由 gai usage --report 根据 .gai/usage.jsonl 生成；再次运行会覆盖同步本文件。",
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
        "footer": "Generated by gai usage --report from .gai/usage.jsonl; re-run overwrites this file.",
    }
