"""Shared dashboard CSS for usage / history HTML reports."""

from __future__ import annotations

# Plain CSS (single braces). Embed via {DASHBOARD_CSS} inside an f-string.
DASHBOARD_CSS = """  :root, html[data-theme="dark"] {
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
  }
  html[data-theme="light"] {
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
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    color: var(--text);
    font-family: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background:
      radial-gradient(900px 420px at 8% -8%, var(--glow-a), transparent 55%),
      radial-gradient(800px 380px at 92% 0%, var(--glow-b), transparent 50%),
      linear-gradient(180deg, var(--bg1), var(--bg0));
  }
  @media (prefers-reduced-motion: no-preference) {
    html.theme-ready body,
    html.theme-ready .kpi,
    html.theme-ready .card,
    html.theme-ready .filters,
    html.theme-ready .toolbar .seg,
    html.theme-ready .toolbar .seg button,
    html.theme-ready .dd-trigger,
    html.theme-ready .dd-menu {
      transition: background .4s cubic-bezier(.22,1,.36,1), color .4s cubic-bezier(.22,1,.36,1),
        border-color .4s cubic-bezier(.22,1,.36,1), box-shadow .4s cubic-bezier(.22,1,.36,1);
    }
    ::view-transition-old(root), ::view-transition-new(root) {
      animation-duration: .4s;
      animation-timing-function: cubic-bezier(.22,1,.36,1);
    }
  }
  .shell {
    max-width: 1240px;
    margin: 0 auto;
    padding: 28px 22px 40px;
  }
  header.hero {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 22px;
  }
  .brand {
    font-size: .78rem;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 8px;
  }
  h1 {
    margin: 0;
    font-size: clamp(1.55rem, 2.4vw, 2rem);
    font-weight: 700;
    letter-spacing: -.02em;
  }
  .meta {
    margin-top: 10px;
    color: var(--muted);
    font-size: .9rem;
    line-height: 1.55;
  }
  .badge {
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
  }
  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
    position: relative;
    z-index: 1;
  }
  .kpi, .card, .filters {
    position: relative;
    isolation: isolate;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 18px;
    box-shadow: var(--shadow-lift);
    backdrop-filter: blur(10px);
  }
  .kpi, .card {
    z-index: 1;
  }
  /* Shine stays behind content — never wash out titles / table text. */
  .kpi::before, .card::before, .filters::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 0;
    border-radius: inherit;
    pointer-events: none;
    background: linear-gradient(180deg, var(--panel-shine), transparent 42%);
    opacity: .55;
  }
  .kpi > *, .card > *, .filters > * {
    position: relative;
    z-index: 1;
  }
  .kpi {
    padding: 16px 16px 14px;
  }
  .kpi .label {
    color: var(--muted);
    font-size: .8rem;
    font-weight: 650;
  }
  .kpi .value {
    margin-top: 8px;
    font-size: 1.45rem;
    font-weight: 760;
    letter-spacing: -.02em;
    color: var(--text);
  }
  .kpi .sub {
    margin-top: 4px;
    color: var(--muted);
    font-size: .78rem;
    font-weight: 550;
  }
  .value.ok { color: var(--ok); }
  .value.fail { color: var(--fail); }
  .grid {
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 14px;
  }
  .card {
    padding: 16px 16px 12px;
    min-width: 0;
  }
  .card.full { grid-column: 1 / -1; }
  .card h2 {
    margin: 0 0 4px;
    font-size: 1.02rem;
    font-weight: 750;
    color: var(--text);
    letter-spacing: -.01em;
  }
  .card .hint {
    color: var(--muted);
    font-size: .84rem;
    font-weight: 600;
    margin-bottom: 6px;
    line-height: 1.45;
  }
  html[data-theme="light"] .card h2,
  html[data-theme="light"] .card-head h2 {
    color: #071526;
  }
  html[data-theme="light"] .card .hint,
  html[data-theme="light"] .kpi .label,
  html[data-theme="light"] .kpi .sub,
  html[data-theme="light"] .meta,
  html[data-theme="light"] footer,
  html[data-theme="light"] th {
    color: #1a2f4a;
  }
  html[data-theme="light"] td {
    color: #0b1b33;
  }
  html[data-theme="light"] .card::before,
  html[data-theme="light"] .kpi::before,
  html[data-theme="light"] .filters::before {
    opacity: .28;
    background: linear-gradient(180deg, rgba(255,255,255,.7), transparent 36%);
  }
  .card-head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 6px;
  }
  .card-head h2 { margin: 0 0 4px; }
  .seg {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .seg button {
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 999px;
    padding: 6px 11px;
    font-size: .75rem;
    cursor: pointer;
    box-shadow: var(--shadow-lift);
  }
  .seg button:hover {
    border-color: var(--accent);
    color: var(--accent);
    transform: translateY(-1px);
  }
  .seg button.active {
    background: var(--seg-active-bg);
    border-color: var(--accent);
    color: var(--seg-active-text);
    font-weight: 650;
    box-shadow: var(--shadow-lift);
  }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    justify-content: flex-end;
    margin: 0 0 12px;
  }
  .toolbar .seg {
    border: 1px solid var(--panel-border);
    background: var(--seg-bg);
    border-radius: 10px;
    overflow: hidden;
    gap: 0;
    box-shadow: var(--shadow-lift);
  }
  .toolbar .seg button {
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    box-shadow: none;
    padding: 8px 12px;
    font-size: .78rem;
    font-weight: 600;
    transform: none;
  }
  .toolbar .seg button:hover {
    color: var(--accent);
    transform: none;
  }
  .toolbar .seg button.active {
    background: var(--text);
    color: var(--on-ink);
    border-color: transparent;
    box-shadow: none;
  }
  .toolbar .btn-refresh {
    border: 1px solid var(--panel-border);
    background: var(--seg-bg);
    color: var(--text);
    border-radius: 10px;
    padding: 8px 14px;
    font-size: .78rem;
    font-weight: 650;
    cursor: pointer;
    box-shadow: var(--shadow-lift);
  }
  .toolbar .btn-refresh:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .toolbar .btn-refresh:disabled {
    opacity: .6;
    cursor: wait;
  }
  .toolbar .btn-export {
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 999px;
    padding: 8px 14px;
    font: inherit;
    font-weight: 650;
    cursor: pointer;
  }
  .toolbar .btn-export:hover { filter: brightness(1.08); }
  button:focus-visible, .dd-trigger:focus-visible, .seg button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .table-tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin: 0 0 10px;
  }
  .pager {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .pager button {
    border: 1px solid var(--panel-border);
    background: var(--seg-btn);
    color: var(--seg-btn-text);
    border-radius: 8px;
    padding: 6px 10px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .pager button:disabled { opacity: .45; cursor: not-allowed; }
  .pager-meta { color: var(--muted); font-size: .85rem; }
  .toast {
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
  }
  .toast.show { opacity: 1; transform: none; }
  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
    margin: 0 0 16px;
    padding: 14px 16px;
    z-index: 40;
    overflow: visible;
  }
  .filters > label {
    color: #cbd5e1;
    font-size: .84rem;
    font-weight: 600;
  }
  .filters > .meta {
    margin: 0;
    flex: 1 1 220px;
  }
  .dd {
    position: relative;
    min-width: min(320px, 100%);
    z-index: 50;
  }
  .dd.open {
    z-index: 60;
  }
  .dd-trigger {
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
  }
  .dd-trigger:hover {
    border-color: var(--accent);
  }
  .dd.open .dd-trigger {
    border-color: var(--accent);
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent),
      var(--shadow-lift);
  }
  .dd-ico {
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
  }
  .dd-label {
    flex: 1 1 auto;
    font-size: .9rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dd-caret {
    width: 8px;
    height: 8px;
    border-right: 2px solid #94a3b8;
    border-bottom: 2px solid #94a3b8;
    transform: rotate(45deg);
    margin: -4px 4px 0 0;
    transition: transform .18s ease;
  }
  .dd.open .dd-caret {
    transform: rotate(225deg);
    margin-top: 2px;
  }
  .dd-menu {
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
  }
  .dd.open .dd-menu { display: block; }
  .dd-item {
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
  }
  .dd-item:hover {
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .dd-item.active {
    background: var(--seg-active-bg);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent) inset;
  }
  .dd-item-text { flex: 1 1 auto; }
  .dd-check {
    opacity: 0;
    color: #7dd3fc;
    font-size: .85rem;
  }
  .dd-item.active .dd-check { opacity: 1; }
  .dd-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: 0 0 auto;
    box-shadow: 0 0 0 3px rgba(255,255,255,.04);
  }
  .dd-dot.all { background: #a78bfa; }
  .dd-dot.repo { background: #38bdf8; }
  /* all = overview across repos; repo = single-repo detail */
  html.view-all .scope-repo,
  html.view-repo .scope-all {
    display: none !important;
  }
  .chart {
    width: 100%;
    height: 300px;
    border-radius: 14px;
    border: 1px solid var(--chart-well-border);
    background: var(--chart-well);
    box-shadow: var(--chart-well-shadow);
  }
  .chart.tall { height: 340px; }
  .table-wrap {
    position: relative;
    z-index: 1;
    overflow-x: auto;
    margin-top: 8px;
    border-radius: 14px;
    border: 1px solid var(--chart-well-border);
    background: var(--table-bg);
    box-shadow: var(--chart-well-shadow);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: .84rem;
    color: var(--text);
  }
  th, td {
    text-align: left;
    padding: 10px 8px;
    border-bottom: 1px solid var(--panel-border);
    vertical-align: top;
    color: inherit;
    opacity: 1;
  }
  th {
    color: var(--muted);
    font-weight: 700;
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--table-head);
  }
  td {
    font-weight: 500;
  }
  tr:hover td { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  .pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: .72rem;
    font-weight: 700;
  }
  .pill.ok { background: rgba(4,120,87,.14); color: var(--ok); }
  .pill.fail { background: rgba(185,28,28,.12); color: var(--fail); }
  html[data-theme="light"] .table-wrap {
    background: #ffffff;
  }
  html[data-theme="light"] .pill.ok {
    background: #d1fae5;
    color: #065f46;
  }
  html[data-theme="light"] .pill.fail {
    background: #fee2e2;
    color: #991b1b;
  }
  .empty {
    display: none;
    padding: 64px 20px;
    text-align: center;
    color: var(--muted);
    background: var(--panel);
    border: 1px dashed var(--panel-border);
    border-radius: 18px;
    box-shadow: var(--shadow-lift);
  }
  footer {
    margin-top: 22px;
    color: var(--muted);
    font-size: .78rem;
  }
  @media (max-width: 920px) {
    .grid { grid-template-columns: 1fr; }
    .chart, .chart.tall { height: 280px; }
    .dd { min-width: 100%; }
  }
"""
