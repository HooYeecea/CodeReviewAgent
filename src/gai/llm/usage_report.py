"""Build a fixed project HTML dashboard from usage.jsonl."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gai.llm.history import UsageRecord, project_root, summarize_records, usage_log_path

_REPORT_RELATIVE = Path(".gai") / "usage-report.html"


def usage_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _REPORT_RELATIVE


def build_usage_analytics(records: list[UsageRecord]) -> dict[str, Any]:
    """Aggregate records into chart-friendly structures."""
    summary = summarize_records(records)
    ok_count = sum(1 for r in records if r.ok is True)
    fail_count = sum(1 for r in records if r.ok is False)
    durations = [r.duration_ms for r in records if r.duration_ms is not None]
    avg_ms = int(sum(durations) / len(durations)) if durations else None

    by_day_tokens: dict[str, int] = defaultdict(int)
    by_day_calls: dict[str, int] = defaultdict(int)
    by_action: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_provider: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    by_user: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})

    for rec in records:
        day = _day_key(rec.ts)
        by_day_calls[day] += 1
        tok = rec.total_tokens or 0
        by_day_tokens[day] += tok

        action = rec.action_detail or rec.action or "(unknown)"
        by_action[action]["calls"] += 1
        by_action[action]["tokens"] += tok

        provider = rec.provider_name or rec.provider or "(unknown)"
        by_provider[provider]["calls"] += 1
        by_provider[provider]["tokens"] += tok

        model = rec.model or "(unknown)"
        by_model[model]["calls"] += 1
        by_model[model]["tokens"] += tok

        if rec.git_user and rec.git_email:
            user = f"{rec.git_user} <{rec.git_email}>"
        else:
            user = rec.git_user or rec.git_email or "(unknown)"
        by_user[user]["calls"] += 1
        by_user[user]["tokens"] += tok

    days = sorted(by_day_calls.keys())
    recent = list(reversed(records[-100:]))

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": str(usage_log_path()),
        "totals": {
            "calls": summary.calls,
            "tokens": summary.total_tokens if summary.total_known else summary.total_tokens,
            "tokens_known": summary.total_known,
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
            "ok": ok_count,
            "fail": fail_count,
            "avg_duration_ms": avg_ms,
        },
        "by_day": {
            "labels": days,
            "calls": [by_day_calls[d] for d in days],
            "tokens": [by_day_tokens[d] for d in days],
        },
        "by_action": _series(by_action),
        "by_provider": _series(by_provider),
        "by_model": _series(by_model),
        "by_user": _series(by_user),
        "recent": [r.to_dict() for r in recent],
    }


def write_usage_report(
    records: list[UsageRecord],
    *,
    chinese: bool = False,
    path: Path | None = None,
) -> Path:
    """Overwrite the fixed HTML report with data synced from usage.jsonl."""
    target = path or usage_report_path()
    analytics = build_usage_analytics(records)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_usage_report_html(analytics, chinese=chinese),
        encoding="utf-8",
    )
    return target


def render_usage_report_html(analytics: dict[str, Any], *, chinese: bool = False) -> str:
    """Self-contained HTML dashboard (Chart.js via CDN)."""
    t = _i18n(chinese)
    payload = json.dumps(analytics, ensure_ascii=False)
    payload_js = json.dumps(payload)
    title = html.escape(t["title"])
    generated = html.escape(str(analytics.get("generated_at") or ""))
    source = html.escape(str(analytics.get("source") or ""))
    totals = analytics.get("totals") or {}

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if chinese else 'en'}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1419;
    --panel: #1a2332;
    --text: #e7ecf3;
    --muted: #9aa7b8;
    --accent: #3d9cf0;
    --ok: #3ecf8e;
    --fail: #f07178;
    --border: #2a3545;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1b2a40 0%, var(--bg) 55%);
    color: var(--text);
    line-height: 1.45;
  }}
  header {{
    padding: 28px 28px 8px;
  }}
  h1 {{ margin: 0 0 8px; font-size: 1.6rem; font-weight: 650; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; }}
  .wrap {{ padding: 12px 28px 40px; }}
  .kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin: 18px 0 22px;
  }}
  .kpi {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
  }}
  .kpi .label {{ color: var(--muted); font-size: 0.8rem; }}
  .kpi .value {{ font-size: 1.35rem; font-weight: 700; margin-top: 4px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 14px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px 18px;
  }}
  .card h2 {{
    margin: 0 0 12px;
    font-size: 1rem;
    font-weight: 600;
  }}
  .chart-box {{ position: relative; height: 260px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }}
  th, td {{
    text-align: left;
    padding: 8px 6px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  th {{ color: var(--muted); font-weight: 600; }}
  .ok {{ color: var(--ok); }}
  .fail {{ color: var(--fail); }}
  .empty {{
    padding: 40px;
    text-align: center;
    color: var(--muted);
  }}
  footer {{
    padding: 0 28px 28px;
    color: var(--muted);
    font-size: 0.8rem;
  }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{t['generated']}: {generated}<br/>{t['source']}: {source}</div>
</header>
<div class="wrap" id="app">
  <div class="empty" id="empty" hidden>{html.escape(t['empty'])}</div>
  <div id="content">
    <div class="kpis">
      <div class="kpi"><div class="label">{t['calls']}</div><div class="value" id="kpi-calls">{totals.get('calls', 0)}</div></div>
      <div class="kpi"><div class="label">{t['tokens']}</div><div class="value" id="kpi-tokens">{totals.get('tokens', 0)}</div></div>
      <div class="kpi"><div class="label">{t['ok']}</div><div class="value ok" id="kpi-ok">{totals.get('ok', 0)}</div></div>
      <div class="kpi"><div class="label">{t['fail']}</div><div class="value fail" id="kpi-fail">{totals.get('fail', 0)}</div></div>
      <div class="kpi"><div class="label">{t['avg_ms']}</div><div class="value" id="kpi-ms">{totals.get('avg_duration_ms') if totals.get('avg_duration_ms') is not None else '—'}</div></div>
    </div>
    <div class="grid">
      <div class="card" style="grid-column: 1 / -1;">
        <h2>{t['by_day']}</h2>
        <div class="chart-box"><canvas id="chart-day"></canvas></div>
      </div>
      <div class="card"><h2>{t['by_action']}</h2><div class="chart-box"><canvas id="chart-action"></canvas></div></div>
      <div class="card"><h2>{t['by_provider']}</h2><div class="chart-box"><canvas id="chart-provider"></canvas></div></div>
      <div class="card"><h2>{t['by_model']}</h2><div class="chart-box"><canvas id="chart-model"></canvas></div></div>
      <div class="card"><h2>{t['by_user']}</h2><div class="chart-box"><canvas id="chart-user"></canvas></div></div>
      <div class="card" style="grid-column: 1 / -1;">
        <h2>{t['recent']}</h2>
        <div style="overflow-x:auto;">
          <table>
            <thead>
              <tr>
                <th>{t['col_time']}</th>
                <th>{t['col_user']}</th>
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
    </div>
  </div>
</div>
<footer>{html.escape(t['footer'])}</footer>
<script>
const DATA = JSON.parse({payload_js});
const I18N = {json.dumps(t, ensure_ascii=False)};

function seriesChart(id, series, color) {{
  const el = document.getElementById(id);
  if (!el) return;
  const labels = series.labels || [];
  const tokens = series.tokens || [];
  new Chart(el, {{
    type: 'bar',
    data: {{
      labels,
      datasets: [{{
        label: I18N.tokens,
        data: tokens,
        backgroundColor: color || '#3d9cf0aa',
        borderColor: color || '#3d9cf0',
        borderWidth: 1,
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ color: '#9aa7b8', maxRotation: 45, minRotation: 0 }}, grid: {{ color: '#2a354555' }} }},
        y: {{ ticks: {{ color: '#9aa7b8' }}, grid: {{ color: '#2a354555' }}, beginAtZero: true }}
      }}
    }}
  }});
}}

(function main() {{
  const totals = DATA.totals || {{}};
  const empty = (totals.calls || 0) === 0;
  document.getElementById('empty').hidden = !empty;
  document.getElementById('content').hidden = empty;
  if (empty) return;

  const day = DATA.by_day || {{}};
  new Chart(document.getElementById('chart-day'), {{
    type: 'line',
    data: {{
      labels: day.labels || [],
      datasets: [
        {{
          label: I18N.tokens,
          data: day.tokens || [],
          borderColor: '#3d9cf0',
          backgroundColor: '#3d9cf033',
          tension: 0.25,
          yAxisID: 'y',
        }},
        {{
          label: I18N.calls,
          data: day.calls || [],
          borderColor: '#3ecf8e',
          backgroundColor: '#3ecf8e33',
          tension: 0.25,
          yAxisID: 'y1',
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      scales: {{
        x: {{ ticks: {{ color: '#9aa7b8' }}, grid: {{ color: '#2a354555' }} }},
        y: {{
          position: 'left',
          ticks: {{ color: '#9aa7b8' }},
          grid: {{ color: '#2a354555' }},
          title: {{ display: true, text: I18N.tokens, color: '#9aa7b8' }},
          beginAtZero: true
        }},
        y1: {{
          position: 'right',
          ticks: {{ color: '#9aa7b8' }},
          grid: {{ drawOnChartArea: false }},
          title: {{ display: true, text: I18N.calls, color: '#9aa7b8' }},
          beginAtZero: true
        }}
      }},
      plugins: {{ legend: {{ labels: {{ color: '#e7ecf3' }} }} }}
    }}
  }});

  seriesChart('chart-action', DATA.by_action, '#f0a35e');
  seriesChart('chart-provider', DATA.by_provider, '#8b7cf0');
  seriesChart('chart-model', DATA.by_model, '#3d9cf0');
  seriesChart('chart-user', DATA.by_user, '#3ecf8e');

  const body = document.getElementById('recent-body');
  for (const r of (DATA.recent || [])) {{
    const tr = document.createElement('tr');
    const who = r.git_user && r.git_email
      ? `${{r.git_user}} <${{r.git_email}}>`
      : (r.git_user || r.git_email || '—');
    const action = r.action_detail || r.action || '—';
    const tokens = r.total_tokens != null ? r.total_tokens : '—';
    const meta = [
      r.branch,
      r.files_count != null ? `${{r.files_count}} files` : '',
      r.commit_count != null ? `${{r.commit_count}} commits` : '',
      r.duration_ms != null ? `${{r.duration_ms}}ms` : '',
    ].filter(Boolean).join(', ') || '—';
    const ok = r.ok === false
      ? `<span class="fail">FAIL${{r.error_kind ? '(' + r.error_kind + ')' : ''}}</span>`
      : (r.ok === true ? `<span class="ok">OK</span>` : '—');
    tr.innerHTML = `
      <td>${{esc(r.ts || '')}}</td>
      <td>${{esc(who)}}</td>
      <td>${{esc(r.provider_name || r.provider || '')}}</td>
      <td>${{esc(r.model || '')}}</td>
      <td>${{esc(action)}}</td>
      <td>${{esc(String(tokens))}}</td>
      <td>${{esc(meta)}}</td>
      <td>${{ok}}</td>`;
    body.appendChild(tr);
  }}
}})();

function esc(s) {{
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}}
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


def _day_key(ts: str) -> str:
    text = (ts or "").strip()
    if not text:
        return "unknown"
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt.date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else "unknown"


def _i18n(chinese: bool) -> dict[str, str]:
    if chinese:
        return {
            "title": "gai Token 用量报告",
            "generated": "生成时间",
            "source": "数据源",
            "empty": "暂无用量数据。请先使用 gai review / commit / report 产生调用，再重新生成报告。",
            "calls": "调用次数",
            "tokens": "Token 合计",
            "ok": "成功",
            "fail": "失败",
            "avg_ms": "平均耗时",
            "by_day": "按日趋势（Token / 调用）",
            "by_action": "按动作（Token）",
            "by_provider": "按厂商（Token）",
            "by_model": "按模型（Token）",
            "by_user": "按用户（Token）",
            "recent": "最近记录（最多 100 条）",
            "col_time": "时间",
            "col_user": "用户",
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
        "ok": "OK",
        "fail": "Failed",
        "avg_ms": "Avg duration",
        "by_day": "Daily trend (tokens / calls)",
        "by_action": "By action (tokens)",
        "by_provider": "By provider (tokens)",
        "by_model": "By model (tokens)",
        "by_user": "By user (tokens)",
        "recent": "Recent records (up to 100)",
        "col_time": "Time",
        "col_user": "User",
        "col_provider": "Provider",
        "col_model": "Model",
        "col_action": "Action",
        "col_tokens": "Tokens",
        "col_meta": "Context",
        "col_status": "Status",
        "footer": "Generated by gai usage --report from .gai/usage.jsonl; re-run overwrites this file.",
    }
