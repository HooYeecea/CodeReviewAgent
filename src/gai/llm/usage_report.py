"""Build a fixed project HTML dashboard from usage.jsonl (ECharts)."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timezone
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
            "tokens": summary.total_tokens,
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
    """Self-contained HTML dashboard powered by ECharts (CDN)."""
    t = _i18n(chinese)
    payload = json.dumps(analytics, ensure_ascii=False)
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

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if chinese else 'en'}">
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

    <div class="empty" id="empty">{html.escape(t['empty'])}</div>

    <div id="content">
      <section class="kpis">
        <div class="kpi">
          <div class="label">{t['calls']}</div>
          <div class="value">{calls}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['tokens']}</div>
          <div class="value">{tokens}</div>
          <div class="sub">{t['prompt']}: {prompt} · {t['completion']}: {completion}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['ok']}</div>
          <div class="value ok">{ok}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['fail']}</div>
          <div class="value fail">{fail}</div>
        </div>
        <div class="kpi">
          <div class="label">{t['avg_ms']}</div>
          <div class="value">{avg_display}</div>
        </div>
      </section>

      <section class="grid">
        <div class="card full">
          <h2>{t['by_day']}</h2>
          <div class="hint">{t['hint_day']}</div>
          <div id="chart-day" class="chart tall"></div>
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
        <div class="card full">
          <h2>{t['recent']}</h2>
          <div class="table-wrap">
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
      </section>
    </div>

    <footer>{html.escape(t['footer'])}</footer>
  </div>

<script>
const DATA = JSON.parse({payload_js});
const I18N = {i18n_js};
const COLORS = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#fb7185', '#2dd4bf'];

function pieData(series) {{
  const labels = series.labels || [];
  const tokens = series.tokens || [];
  return labels.map((name, i) => ({{ name, value: tokens[i] || 0 }}));
}}

function baseText() {{
  return {{ color: '#94a3b8', fontSize: 11 }};
}}

function initDayChart() {{
  const el = document.getElementById('chart-day');
  const chart = echarts.init(el, null, {{ renderer: 'canvas' }});
  const day = DATA.by_day || {{}};
  chart.setOption({{
    color: ['#38bdf8', '#34d399'],
    tooltip: {{ trigger: 'axis' }},
    legend: {{
      data: [I18N.tokens, I18N.calls],
      textStyle: {{ color: '#cbd5e1' }},
      top: 0
    }},
    grid: {{ left: 48, right: 48, top: 42, bottom: 36 }},
    xAxis: {{
      type: 'category',
      data: day.labels || [],
      boundaryGap: false,
      axisLabel: baseText(),
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
        symbol: 'circle',
        symbolSize: 7,
        areaStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: 'rgba(56,189,248,.35)' }},
            {{ offset: 1, color: 'rgba(56,189,248,.02)' }}
          ])
        }},
        data: day.tokens || []
      }},
      {{
        name: I18N.calls,
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        symbol: 'circle',
        symbolSize: 7,
        data: day.calls || []
      }}
    ]
  }});
  return chart;
}}

function initPie(id, series) {{
  const chart = echarts.init(document.getElementById(id));
  chart.setOption({{
    color: COLORS,
    tooltip: {{
      trigger: 'item',
      formatter: function (p) {{
        return p.name + '<br/>' + p.value + ' (' + I18N.tokens + ') · ' + p.percent + '%';
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
      data: pieData(series)
    }}]
  }});
  return chart;
}}

function initBar(id, series) {{
  const chart = echarts.init(document.getElementById(id));
  const labels = (series.labels || []).slice();
  const tokens = (series.tokens || []).slice();
  chart.setOption({{
    color: ['#a78bfa'],
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
    grid: {{ left: 16, right: 24, top: 24, bottom: 24, containLabel: true }},
    xAxis: {{
      type: 'value',
      axisLabel: baseText(),
      splitLine: {{ lineStyle: {{ color: 'rgba(148,163,184,.12)' }} }}
    }},
    yAxis: {{
      type: 'category',
      data: labels,
      axisLabel: {{ ...baseText(), width: 120, overflow: 'truncate' }},
      axisLine: {{ lineStyle: {{ color: '#334155' }} }}
    }},
    series: [{{
      type: 'bar',
      data: tokens,
      barMaxWidth: 22,
      itemStyle: {{
        borderRadius: [0, 8, 8, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          {{ offset: 0, color: '#6366f1' }},
          {{ offset: 1, color: '#38bdf8' }}
        ])
      }}
    }}]
  }});
  return chart;
}}

function fillTable() {{
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

(function main() {{
  const totals = DATA.totals || {{}};
  const empty = (totals.calls || 0) === 0;
  document.getElementById('empty').style.display = empty ? 'block' : 'none';
  document.getElementById('content').style.display = empty ? 'none' : 'block';
  if (empty) return;

  const charts = [
    initDayChart(),
    initPie('chart-action', DATA.by_action || {{}}),
    initPie('chart-provider', DATA.by_provider || {{}}),
    initBar('chart-model', DATA.by_model || {{}}),
    initBar('chart-user', DATA.by_user || {{}}),
  ];
  fillTable();
  window.addEventListener('resize', () => charts.forEach(c => c.resize()));
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
            "prompt": "输入",
            "completion": "输出",
            "ok": "成功",
            "fail": "失败",
            "avg_ms": "平均耗时",
            "by_day": "按日趋势",
            "by_action": "按动作分布",
            "by_provider": "按厂商分布",
            "by_model": "按模型用量",
            "by_user": "按用户用量",
            "hint_day": "双轴：Token 与调用次数",
            "hint_pie": "环形图按 Token 占比",
            "hint_bar": "横向柱状图按 Token",
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
        "prompt": "Prompt",
        "completion": "Completion",
        "ok": "OK",
        "fail": "Failed",
        "avg_ms": "Avg duration",
        "by_day": "Daily trend",
        "by_action": "By action",
        "by_provider": "By provider",
        "by_model": "By model",
        "by_user": "By user",
        "hint_day": "Dual axis: tokens and call count",
        "hint_pie": "Donut chart by token share",
        "hint_bar": "Horizontal bars by tokens",
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
