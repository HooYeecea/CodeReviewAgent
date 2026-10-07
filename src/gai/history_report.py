"""Build a fixed project HTML dashboard from commands.jsonl (ECharts)."""

from __future__ import annotations

import html
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gai.command_history import CommandRecord, command_log_path, load_command_records
from gai.llm.history import project_root
from gai.llm.usage_report import path_to_file_url
from gai.web_prefs import PREF_LANG, PREF_THEME, early_prefs_script

_REPORT_RELATIVE = Path(".gai") / "history-report.html"
_DATA_RELATIVE = Path(".gai") / "history-data.js"
_SYNC_MIN_INTERVAL_SEC = 2.0

__all__ = [
    "build_history_analytics",
    "build_history_datasets",
    "history_data_path",
    "history_report_path",
    "path_to_file_url",
    "render_history_report_html",
    "sync_history_data_file",
    "write_history_data_js",
    "write_history_report",
]


def history_report_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _REPORT_RELATIVE


def history_data_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _DATA_RELATIVE


def write_history_data_js(
    datasets: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    target = path or history_data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(datasets, ensure_ascii=False)
    target.write_text(
        "window.__GAI_HISTORY_DATASETS__ = " + payload + ";\n",
        encoding="utf-8",
    )
    return target


def sync_history_data_file(
    *,
    log_path: Path | None = None,
    force: bool = False,
    ensure_html: bool = True,
) -> Path | None:
    """Rebuild history-data.js from commands.jsonl (best-effort; never raises)."""
    try:
        data_path = (
            log_path.parent / "history-data.js"
            if log_path is not None
            else history_data_path()
        )
        if (
            not force
            and data_path.is_file()
            and (time.time() - data_path.stat().st_mtime) < _SYNC_MIN_INTERVAL_SEC
        ):
            return data_path
        records = load_command_records(path=log_path)
        datasets = build_history_datasets(records)
        written = write_history_data_js(datasets, path=data_path)
        if ensure_html:
            html_path = data_path.parent / "history-report.html"
            if not html_path.is_file():
                html_path.write_text(
                    render_history_report_html(datasets, chinese=False),
                    encoding="utf-8",
                )
        return written
    except Exception:
        return None


def write_history_report(
    records: list[CommandRecord],
    *,
    chinese: bool = False,
    path: Path | None = None,
) -> Path:
    target = path or history_report_path()
    datasets = build_history_datasets(records)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_history_data_js(datasets, path=target.parent / "history-data.js")
    target.write_text(
        render_history_report_html(datasets, chinese=chinese),
        encoding="utf-8",
    )
    return target


def build_history_datasets(records: list[CommandRecord]) -> dict[str, Any]:
    labels: dict[str, str] = {}
    for rec in records:
        key = _project_key(rec)
        labels[key] = _project_label(rec)

    by_project: dict[str, dict[str, Any]] = {}
    for key in labels:
        subset = [r for r in records if _project_key(r) == key]
        by_project[key] = build_history_analytics(subset)

    return {
        "all": build_history_analytics(records),
        "by_project": by_project,
        "projects": [{"id": key, "label": labels[key]} for key in sorted(labels.keys())],
        "default_project": "__all__",
    }


def build_history_analytics(records: list[CommandRecord]) -> dict[str, Any]:
    ok_count = sum(1 for r in records if r.ok)
    fail_count = len(records) - ok_count
    durations = [r.duration_ms for r in records if r.duration_ms is not None]
    avg_ms = int(sum(durations) / len(durations)) if durations else None

    by_command: dict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "ok": 0, "fail": 0, "duration_sum": 0, "duration_n": 0}
    )
    by_user: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "ok": 0, "fail": 0})
    by_repo: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "ok": 0, "fail": 0})
    heat_repo: dict[tuple[str, str], int] = defaultdict(int)
    cmd_durations: dict[str, list[int]] = defaultdict(list)

    for rec in records:
        cmd = _command_label(rec)
        by_command[cmd]["calls"] += 1
        if rec.ok:
            by_command[cmd]["ok"] += 1
        else:
            by_command[cmd]["fail"] += 1
        if rec.duration_ms is not None:
            by_command[cmd]["duration_sum"] += rec.duration_ms
            by_command[cmd]["duration_n"] += 1
            cmd_durations[cmd].append(rec.duration_ms)

        if rec.git_user and rec.git_email:
            user = f"{rec.git_user} <{rec.git_email}>"
        else:
            user = rec.git_user or rec.git_email or "(unknown)"
        by_user[user]["calls"] += 1
        if rec.ok:
            by_user[user]["ok"] += 1
        else:
            by_user[user]["fail"] += 1

        repo = _project_key(rec)
        by_repo[repo]["calls"] += 1
        if rec.ok:
            by_repo[repo]["ok"] += 1
        else:
            by_repo[repo]["fail"] += 1
        heat_repo[(repo, cmd)] += 1

    trends = _build_trend_series(records)
    commands = sorted(by_command.keys(), key=lambda c: (-by_command[c]["calls"], c))
    repos = sorted(by_repo.keys(), key=lambda r: (-by_repo[r]["calls"], r))
    heatmap_repo_data = [
        [commands.index(c), repos.index(r), heat_repo[(r, c)]]
        for r, c in heat_repo
        if heat_repo[(r, c)] > 0 and c in commands and r in repos
    ]

    recent = list(reversed(records[-100:]))
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": str(command_log_path()),
        "totals": {
            "calls": len(records),
            "ok": ok_count,
            "fail": fail_count,
            "avg_duration_ms": avg_ms,
        },
        "trends": trends,
        "default_trend": "today",
        "by_command": _count_series(by_command),
        "by_user": _count_series(by_user),
        "by_repo": _count_series(by_repo),
        "by_status": {
            "labels": ["ok", "fail"],
            "calls": [ok_count, fail_count],
        },
        "duration_by_command": _duration_series(cmd_durations),
        "heatmap_repo": {
            "repos": repos,
            "commands": commands,
            "data": heatmap_repo_data,
        },
        "recent": [r.to_dict() for r in recent],
    }


def _command_label(rec: CommandRecord) -> str:
    name = (rec.command or "").strip() or "(unknown)"
    sub = (rec.subcommand or "").strip()
    return f"{name} {sub}".strip() if sub else name


def _project_key(rec: CommandRecord) -> str:
    return (rec.repo_name or "").strip() or "(unknown)"


def _project_label(rec: CommandRecord) -> str:
    key = _project_key(rec)
    if rec.remote_name:
        return f"{key} · {rec.remote_name}"
    return key


def _count_series(bucket: dict[str, dict[str, int]]) -> dict[str, list[Any]]:
    items = sorted(bucket.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))
    return {
        "labels": [k for k, _ in items],
        "calls": [v["calls"] for _, v in items],
        "ok": [v.get("ok", 0) for _, v in items],
        "fail": [v.get("fail", 0) for _, v in items],
    }


def _duration_series(model_durations: dict[str, list[int]]) -> dict[str, list[Any]]:
    items = sorted(
        (
            (name, int(sum(vals) / len(vals)))
            for name, vals in model_durations.items()
            if vals
        ),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return {
        "labels": [k for k, _ in items],
        "avg_ms": [v for _, v in items],
    }


def _build_trend_series(
    records: list[CommandRecord],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, list[Any]]]:
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
        parsed.append((dt, 1))

    today = now.date()
    today_labels = [f"{h:02d}:00" for h in range(0, now.hour + 1)]
    today_calls = [0] * len(today_labels)
    for dt, _ in parsed:
        if dt.date() != today:
            continue
        idx = dt.hour
        if 0 <= idx < len(today_labels):
            today_calls[idx] += 1

    return {
        "today": {
            "labels": today_labels,
            "calls": today_calls,
            "title_key": "trend_today",
        },
        "last7": {**_rolling_day_series(parsed, today=today, days=7), "title_key": "trend_last7"},
        "last15": {
            **_rolling_day_series(parsed, today=today, days=15),
            "title_key": "trend_last15",
        },
        "week": {
            **_bucket_series(
                parsed,
                key_fn=lambda dt: f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}",
            ),
            "title_key": "trend_week",
        },
        "month": {
            **_bucket_series(parsed, key_fn=lambda dt: dt.strftime("%Y-%m")),
            "title_key": "trend_month",
        },
        "year": {
            **_bucket_series(parsed, key_fn=lambda dt: dt.strftime("%Y")),
            "title_key": "trend_year",
        },
        "all_days": {
            **_bucket_series(
                parsed,
                key_fn=lambda dt: dt.date().isoformat(),
                fill_keys=_all_day_keys(parsed),
            ),
            "title_key": "trend_all_days",
        },
    }


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
    keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return _bucket_series(
        parsed,
        key_fn=lambda dt: dt.date().isoformat(),
        fill_keys=keys,
    )


def _all_day_keys(parsed: list[tuple[datetime, int]]) -> list[str]:
    if not parsed:
        return []
    days = sorted({dt.date() for dt, _ in parsed})
    if not days:
        return []
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
    bucket: dict[str, int] = defaultdict(int)
    for dt, n in parsed:
        bucket[key_fn(dt)] += n
    labels = fill_keys if fill_keys is not None else sorted(bucket.keys())
    return {"labels": labels, "calls": [bucket.get(k, 0) for k in labels]}


def _i18n(chinese: bool) -> dict[str, str]:
    if chinese:
        return {
            "title": "gai 命令执行报告",
            "generated": "生成时间",
            "source": "数据源",
            "empty": "暂无命令执行记录。请先运行任意 gai 子命令，再刷新或重新生成报告。",
            "calls": "执行次数",
            "ok": "成功",
            "fail": "失败",
            "avg_ms": "平均耗时",
            "trend_title": "执行趋势",
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
            "hint_project": "按仓库筛选；远程与仓库绑定",
            "hint_project_all": "总览：跨仓库对比（按仓库次数、仓库×命令）",
            "hint_project_repo": "单仓详情：该仓库内的命令分布与耗时",
            "by_repo": "按仓库次数",
            "hint_repo": "全部项目总览：对比各仓库命令执行次数",
            "heatmap_repo": "仓库 × 命令（次数热力图）",
            "hint_heat_repo": "颜色越亮表示该仓库上该命令执行越多",
            "by_status": "成功 / 失败",
            "by_command": "按命令分布",
            "by_user": "按用户次数",
            "duration_by_command": "按命令平均耗时",
            "hint_day": "按执行次数统计",
            "hint_pie": "环形图按次数占比",
            "hint_bar": "横向柱状图按次数",
            "hint_duration": "单位：毫秒（ms）",
            "recent": "最近记录（最多 100 条）",
            "col_time": "时间",
            "col_user": "用户",
            "col_repo": "仓库",
            "col_command": "命令",
            "col_argv": "参数",
            "col_status": "状态",
            "col_ms": "耗时",
            "refresh": "刷新",
            "refreshing": "刷新中…",
            "refresh_ok": "已更新到最新命令记录",
            "refresh_fail": "刷新失败：找不到 history-data.js",
            "refresh_fail_file": "刷新失败：file:// 下可能被浏览器拦截。请改用 gai history --serve，或确认同目录有 history-data.js",
            "refresh_fail_http": "刷新失败：找不到 history-data.js。请先执行 gai history --report",
            "export_csv": "导出 CSV",
            "export_ok": "已导出 CSV",
            "page_prev": "上一页",
            "page_next": "下一页",
            "page_of": "第 {{page}}/{{pages}} 页 · {{shown}}",
            "theme_light": "日间",
            "theme_dark": "夜间",
            "footer": "数据来自 .gai/commands.jsonl（同步为 history-data.js）。点「刷新」可加载最新数据；日常 gai 调用也会自动更新。file:// 不稳时用 gai history --serve。",
        }
    return {
        "title": "gai Command History Report",
        "generated": "Generated",
        "source": "Source",
        "empty": "No command history yet. Run any gai subcommand, then refresh or regenerate.",
        "calls": "Runs",
        "ok": "OK",
        "fail": "Failed",
        "avg_ms": "Avg duration",
        "trend_title": "Run trend",
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
        "hint_project": "Filter by repo; remote is bound to repo",
        "hint_project_all": "Overview: compare across repos (by repo, repo×command)",
        "hint_project_repo": "Repo detail: command mix and duration in this repo",
        "by_repo": "By repository",
        "hint_repo": "All-projects overview: compare run counts by repo",
        "heatmap_repo": "Repo × command heatmap (runs)",
        "hint_heat_repo": "Brighter means more runs for that command in that repo",
        "by_status": "Success / failure",
        "by_command": "By command",
        "by_user": "By user",
        "duration_by_command": "Avg duration by command",
        "hint_day": "Run counts over time",
        "hint_pie": "Donut chart by run share",
        "hint_bar": "Horizontal bars by runs",
        "hint_duration": "Unit: milliseconds (ms)",
        "recent": "Recent records (up to 100)",
        "col_time": "Time",
        "col_user": "User",
        "col_repo": "Repo",
        "col_command": "Command",
        "col_argv": "Args",
        "col_status": "Status",
        "col_ms": "Duration",
        "refresh": "Refresh",
        "refreshing": "Refreshing…",
        "refresh_ok": "Command history updated",
        "refresh_fail": "Refresh failed: history-data.js missing",
        "refresh_fail_file": "Refresh failed: browsers may block file:// script reloads. Use gai history --serve.",
        "refresh_fail_http": "Refresh failed: history-data.js missing. Run gai history --report first.",
        "export_csv": "Export CSV",
        "export_ok": "CSV exported",
        "page_prev": "Prev",
        "page_next": "Next",
        "page_of": "Page {{page}}/{{pages}} · {{shown}}",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "footer": "Data from .gai/commands.jsonl (synced to history-data.js). Click Refresh for the latest snapshot; normal gai runs also update the data file. Prefer gai history --serve if file:// refresh is blocked.",
    }


def render_history_report_html(datasets: dict[str, Any], *, chinese: bool = False) -> str:
    """HTML dashboard powered by ECharts; datasets load from history-data.js."""
    t = _i18n(chinese)
    i18n_js = json.dumps({"cn": _i18n(True), "en": _i18n(False)}, ensure_ascii=False)
    initial_lang = "cn" if chinese else "en"
    title = html.escape(t["title"])
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
<script src="history-data.js"></script>
<style>
  :root, html[data-theme="dark"] {{
    --bg0: #07101d; --bg1: #101a2c;
    --panel: linear-gradient(165deg, rgba(36, 48, 72, .96), rgba(18, 28, 46, .96));
    --panel-flat: rgba(22, 32, 51, 0.94);
    --panel-border: rgba(148, 163, 184, 0.22);
    --panel-shine: rgba(255, 255, 255, 0.08);
    --text: #e8eef8; --muted: #94a3b8;
    --accent: #38bdf8; --accent2: #a78bfa;
    --ok: #34d399; --fail: #f87171;
    --top-bg: rgba(7, 16, 29, .72);
    --seg-bg: rgba(15, 23, 42, .7);
    --seg-btn: linear-gradient(180deg, rgba(40, 54, 78, .95), rgba(18, 28, 46, .95));
    --seg-btn-text: #cbd5e1;
    --seg-active-bg: linear-gradient(180deg, rgba(56,189,248,.28), rgba(56,189,248,.1));
    --seg-active-text: #bae6fd;
    --on-ink: #0b1220;
    --chart-well: linear-gradient(180deg, rgba(8,14,26,.45), rgba(8,14,26,.18));
    --table-head: rgba(15, 23, 42, .85);
    --table-row: rgba(255,255,255,.03);
    --badge-bg: linear-gradient(180deg, rgba(56,189,248,.16), rgba(56,189,248,.06));
    --badge-border: rgba(56,189,248,.35);
    --badge-text: #bae6fd;
    --shadow-deep: 0 22px 48px rgba(0, 0, 0, .45), 0 2px 0 rgba(255,255,255,.04) inset;
    --shadow-lift: 0 10px 28px rgba(0, 0, 0, .35), 0 1px 0 rgba(255,255,255,.06) inset, 0 -1px 0 rgba(0,0,0,.35) inset;
    --glow-a: rgba(56,189,248,.18);
    --glow-b: rgba(167,139,250,.16);
  }}
  html[data-theme="light"] {{
    --bg0: #e8eef6; --bg1: #f5f8fc;
    --panel: linear-gradient(165deg, #ffffff, #f2f6fb);
    --panel-flat: #ffffff;
    --panel-border: #c5d0de;
    --panel-shine: rgba(255, 255, 255, 0.95);
    --text: #0b1b33; --muted: #334155;
    --accent: #0f766e; --accent2: #0369a1;
    --ok: #047857; --fail: #b91c1c;
    --top-bg: rgba(245, 248, 252, .92);
    --seg-bg: #ffffff;
    --seg-btn: linear-gradient(180deg, #ffffff, #e8eef6);
    --seg-btn-text: #1e3350;
    --seg-active-bg: linear-gradient(180deg, #ccfbf1, #e6fffa);
    --seg-active-text: #115e59;
    --on-ink: #ffffff;
    --chart-well: linear-gradient(180deg, #ffffff, #f1f5f9);
    --table-head: #e8eef6;
    --table-row: rgba(15,23,42,.03);
    --badge-bg: linear-gradient(180deg, #ccfbf1, #e6fffa);
    --badge-border: rgba(15,118,110,.35);
    --badge-text: #115e59;
    --shadow-deep: 0 18px 40px rgba(16,35,63,.08), 0 1px 0 rgba(255,255,255,.9) inset;
    --shadow-lift: 0 12px 28px rgba(16,35,63,.08), 0 1px 0 rgba(255,255,255,.95) inset;
    --glow-a: rgba(15,118,110,.10);
    --glow-b: rgba(2,132,199,.08);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh;
    font: 15px/1.5 "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    color: var(--text);
    background:
      radial-gradient(900px 420px at 8% -8%, var(--glow-a), transparent 55%),
      radial-gradient(800px 380px at 92% 0%, var(--glow-b), transparent 50%),
      linear-gradient(180deg, var(--bg1), var(--bg0));
  }}
  .shell {{ max-width: 1240px; margin: 0 auto; padding: 28px 22px 40px; }}
  header.hero {{
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px;
    margin-bottom: 22px;
  }}
  .brand {{
    font-size: .78rem; letter-spacing: .14em; text-transform: uppercase;
    color: var(--accent); margin-bottom: 8px;
  }}
  h1 {{
    margin: 0; font-size: clamp(1.55rem, 2.4vw, 2rem); font-weight: 700;
    letter-spacing: -.02em;
  }}
  .meta {{
    margin-top: 10px; color: var(--muted); font-size: .9rem; line-height: 1.55;
  }}
  .badge {{
    align-self: flex-start; padding: 8px 12px; border-radius: 12px;
    border: 1px solid var(--badge-border); background: var(--badge-bg);
    box-shadow: var(--shadow-lift); color: var(--badge-text);
    font-size: .82rem; font-weight: 650; white-space: nowrap;
  }}
  .toolbar {{
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    justify-content: flex-end; margin: 0 0 12px;
  }}
  .toolbar .seg {{
    display: inline-flex; border: 1px solid var(--panel-border); background: var(--seg-bg);
    border-radius: 10px; overflow: hidden; gap: 0; box-shadow: var(--shadow-lift);
  }}
  .toolbar .seg button {{
    border: 0; border-radius: 0; background: transparent; color: var(--muted);
    box-shadow: none; padding: 8px 12px; font-size: .78rem; font-weight: 600;
    cursor: pointer; font-family: inherit;
  }}
  .toolbar .seg button:hover {{ color: var(--accent); }}
  .toolbar .seg button.active {{
    background: var(--text); color: var(--on-ink); border-color: transparent;
  }}
  .toolbar .btn-refresh, .toolbar .btn-export {{
    border: 1px solid var(--panel-border); background: var(--seg-bg); color: var(--text);
    border-radius: 10px; padding: 8px 14px; font-size: .78rem; font-weight: 650;
    cursor: pointer; box-shadow: var(--shadow-lift); font-family: inherit;
  }}
  .toolbar .btn-refresh:hover, .toolbar .btn-export:hover {{
    border-color: var(--accent); color: var(--accent);
  }}
  .toolbar .btn-refresh:disabled {{ opacity: .6; cursor: wait; }}
  button:focus-visible, .dd-trigger:focus-visible, .seg button:focus-visible {{
    outline: 2px solid var(--accent); outline-offset: 2px;
  }}
  .kpi, .card, .filters {{
    position: relative; isolation: isolate; background: var(--panel);
    border: 1px solid var(--panel-border); border-radius: 18px;
    box-shadow: var(--shadow-lift); backdrop-filter: blur(10px);
  }}
  .kpi::before, .card::before, .filters::before {{
    content: ""; position: absolute; inset: 0; z-index: 0; border-radius: inherit;
    pointer-events: none;
    background: linear-gradient(180deg, var(--panel-shine), transparent 42%);
    opacity: .55;
  }}
  .kpi > *, .card > *, .filters > * {{ position: relative; z-index: 1; }}
  html[data-theme="light"] .filters::before,
  html[data-theme="light"] .kpi::before,
  html[data-theme="light"] .card::before {{
    opacity: .28;
    background: linear-gradient(180deg, rgba(255,255,255,.7), transparent 36%);
  }}
  .filters {{
    display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
    margin: 0 0 16px; padding: 14px 16px; z-index: 40; overflow: visible;
  }}
  .filters > label {{
    color: #cbd5e1; font-size: .84rem; font-weight: 600;
  }}
  html[data-theme="light"] .filters > label {{ color: #1e3350; }}
  .filters > .meta {{ margin: 0; flex: 1 1 220px; }}
  .dd {{
    position: relative; min-width: min(320px, 100%); z-index: 50;
  }}
  .dd.open {{ z-index: 60; }}
  .dd-trigger {{
    width: 100%; display: flex; align-items: center; gap: 10px;
    border: 1px solid var(--panel-border); border-radius: 14px; padding: 11px 12px;
    color: var(--text); cursor: pointer; text-align: left; background: var(--seg-btn);
    box-shadow: var(--shadow-lift); font: inherit;
  }}
  .dd-trigger:hover {{ border-color: var(--accent); }}
  .dd.open .dd-trigger {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent), var(--shadow-lift);
  }}
  .dd-ico {{
    width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center;
    background: var(--seg-active-bg); border: 1px solid var(--badge-border);
    box-shadow: 0 1px 0 rgba(255,255,255,.35) inset; color: var(--badge-text);
    font-size: .85rem; flex: 0 0 auto;
  }}
  .dd-label {{
    flex: 1 1 auto; font-size: .9rem; font-weight: 600;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .dd-caret {{
    width: 8px; height: 8px; border-right: 2px solid #94a3b8; border-bottom: 2px solid #94a3b8;
    transform: rotate(45deg); margin: -4px 4px 0 0; transition: transform .18s ease;
  }}
  .dd.open .dd-caret {{ transform: rotate(225deg); margin-top: 2px; }}
  .dd-menu {{
    position: absolute; left: 0; right: 0; top: calc(100% + 8px); z-index: 70;
    display: none; padding: 8px; border-radius: 14px; border: 1px solid var(--panel-border);
    background: var(--panel); box-shadow: var(--shadow-deep); max-height: 280px; overflow: auto;
  }}
  .dd.open .dd-menu {{ display: block; }}
  .dd-item {{
    width: 100%; display: flex; align-items: center; gap: 10px; border: 0;
    border-radius: 10px; background: transparent; color: var(--text);
    padding: 10px 10px; cursor: pointer; text-align: left; font-size: .88rem; font: inherit;
  }}
  .dd-item:hover {{ background: color-mix(in srgb, var(--accent) 12%, transparent); }}
  .dd-item.active {{
    background: var(--seg-active-bg);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent) inset;
  }}
  .dd-item-text {{ flex: 1 1 auto; }}
  .dd-check {{ opacity: 0; color: #7dd3fc; font-size: .85rem; }}
  .dd-item.active .dd-check {{ opacity: 1; }}
  .dd-dot {{
    width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto;
    box-shadow: 0 0 0 3px rgba(255,255,255,.04);
  }}
  .dd-dot.all {{ background: #a78bfa; }}
  .dd-dot.repo {{ background: #38bdf8; }}
  .kpis {{
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px;
  }}
  .kpi {{ padding: 16px 16px 14px; z-index: 1; }}
  .kpi .label {{ color: var(--muted); font-size: .8rem; font-weight: 650; }}
  .kpi .value {{ margin-top: 8px; font-size: 1.45rem; font-weight: 760; letter-spacing: -.02em; }}
  .kpi .sub {{ color: var(--muted); font-size: .78rem; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
  .card {{ padding: 16px 16px 12px; min-width: 0; z-index: 1; }}
  .card.full {{ grid-column: 1 / -1; }}
  .card h2 {{ margin: 0 0 4px; font-size: 1.02rem; font-weight: 750; }}
  .hint {{ color: var(--muted); font-size: .84rem; font-weight: 600; margin-bottom: 6px; }}
  .chart {{ height: 280px; border-radius: 14px; background: var(--chart-well); border: 1px solid var(--panel-border); }}
  .chart.tall {{ height: 340px; }}
  .trend-seg {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 8px; }}
  .trend-seg button {{
    border: 1px solid var(--panel-border); background: var(--seg-btn); color: var(--seg-btn-text);
    border-radius: 999px; padding: 6px 11px; font: inherit; font-size: .75rem; cursor: pointer;
    box-shadow: var(--shadow-lift);
  }}
  .trend-seg button.active {{
    background: var(--seg-active-bg); border-color: var(--accent); color: var(--seg-active-text); font-weight: 650;
  }}
  html.view-all .scope-repo, html.view-repo .scope-all {{ display: none !important; }}
  .table-tools {{
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
    gap: 10px; margin: 0 0 10px;
  }}
  .pager {{ display: inline-flex; align-items: center; gap: 8px; }}
  .pager button {{
    border: 1px solid var(--panel-border); background: var(--seg-btn); color: var(--seg-btn-text);
    border-radius: 8px; padding: 6px 10px; font: inherit; font-weight: 600; cursor: pointer;
  }}
  .pager button:disabled {{ opacity: .45; cursor: not-allowed; }}
  .pager-meta {{ color: var(--muted); font-size: .85rem; }}
  .table-wrap {{ overflow: auto; border-radius: 14px; border: 1px solid var(--panel-border); }}
  table {{ width: 100%; border-collapse: collapse; font-size: .84rem; }}
  th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--panel-border); }}
  th {{ background: var(--table-head); color: var(--muted); font-weight: 700; position: sticky; top: 0; }}
  tr:nth-child(even) td {{ background: var(--table-row); }}
  .pill {{
    display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: .74rem; font-weight: 700;
  }}
  .pill.ok {{ background: rgba(52,211,153,.16); color: var(--ok); }}
  .pill.fail {{ background: rgba(248,113,113,.16); color: var(--fail); }}
  footer {{ margin-top: 18px; color: var(--muted); font-size: .78rem; }}
  .toast {{
    position: fixed; bottom: 22px; right: 22px; z-index: 80; padding: 10px 16px; border-radius: 10px;
    background: var(--text); color: var(--on-ink); font-weight: 650; font-size: .85rem;
    opacity: 0; transform: translateY(6px); pointer-events: none;
    transition: opacity .2s ease, transform .2s ease;
  }}
  .toast.show {{ opacity: 1; transform: none; }}
  @media (max-width: 960px) {{
    .kpis, .grid {{ grid-template-columns: 1fr; }}
    .dd {{ min-width: 100%; }}
  }}
</style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <div class="brand">GAI HISTORY</div>
        <h1 data-i="title">{title}</h1>
        <div class="meta" id="meta-line"></div>
      </div>
      <div class="badge">ECharts · .gai/history-report.html</div>
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
        <div class="dd-menu" id="project-dd-menu" role="listbox" aria-labelledby="project-filter-label"></div>
      </div>
      <span class="meta" id="project-hint" data-i="hint_project">{html.escape(t['hint_project'])}</span>
    </div>

    <section class="kpis">
      <div class="kpi"><div class="label" data-i="calls">{t['calls']}</div><div class="value" id="kpi-calls">0</div></div>
      <div class="kpi"><div class="label" data-i="ok">{t['ok']}</div><div class="value" id="kpi-ok">0</div></div>
      <div class="kpi"><div class="label" data-i="fail">{t['fail']}</div><div class="value" id="kpi-fail">0</div></div>
      <div class="kpi"><div class="label" data-i="avg_ms">{t['avg_ms']}</div><div class="value" id="kpi-ms">—</div></div>
    </section>

    <div class="grid">
      <div class="card full">
        <h2 data-i="trend_title">{t['trend_title']}</h2>
        <div class="hint" id="trend-hint" data-i="hint_day">{t['hint_day']}</div>
        <div class="trend-seg" id="trend-seg">
          <button type="button" data-mode="today" data-i="seg_today">{t['seg_today']}</button>
          <button type="button" data-mode="last7" data-i="seg_last7">{t['seg_last7']}</button>
          <button type="button" data-mode="last15" data-i="seg_last15">{t['seg_last15']}</button>
          <button type="button" data-mode="week" data-i="seg_week">{t['seg_week']}</button>
          <button type="button" data-mode="month" data-i="seg_month">{t['seg_month']}</button>
          <button type="button" data-mode="year" data-i="seg_year">{t['seg_year']}</button>
          <button type="button" data-mode="all_days" data-i="seg_all_days">{t['seg_all_days']}</button>
        </div>
        <div id="chart-trend" class="chart"></div>
      </div>

      <div class="card">
        <h2 data-i="by_command">{t['by_command']}</h2>
        <div class="hint" data-i="hint_bar">{t['hint_bar']}</div>
        <div id="chart-command" class="chart"></div>
      </div>
      <div class="card">
        <h2 data-i="by_status">{t['by_status']}</h2>
        <div class="hint" data-i="hint_pie">{t['hint_pie']}</div>
        <div id="chart-status" class="chart"></div>
      </div>
      <div class="card">
        <h2 data-i="by_user">{t['by_user']}</h2>
        <div class="hint" data-i="hint_bar">{t['hint_bar']}</div>
        <div id="chart-user" class="chart"></div>
      </div>
      <div class="card">
        <h2 data-i="duration_by_command">{t['duration_by_command']}</h2>
        <div class="hint" data-i="hint_duration">{t['hint_duration']}</div>
        <div id="chart-duration" class="chart"></div>
      </div>

      <div class="card full scope-all">
        <h2 data-i="by_repo">{t['by_repo']}</h2>
        <div class="hint" data-i="hint_repo">{t['hint_repo']}</div>
        <div id="chart-repo" class="chart"></div>
      </div>
      <div class="card full scope-all">
        <h2 data-i="heatmap_repo">{t['heatmap_repo']}</h2>
        <div class="hint" data-i="hint_heat_repo">{t['hint_heat_repo']}</div>
        <div id="chart-heat-repo" class="chart tall"></div>
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
                <th data-i="col_command">{t['col_command']}</th>
                <th data-i="col_argv">{t['col_argv']}</th>
                <th data-i="col_status">{t['col_status']}</th>
                <th data-i="col_ms">{t['col_ms']}</th>
              </tr>
            </thead>
            <tbody id="recent-body"></tbody>
          </table>
        </div>
      </div>
    </div>
    <footer data-i="footer">{html.escape(t['footer'])}</footer>
  </div>
  <div class="toast" id="toast"></div>

<script>
const I18N_ALL = {i18n_js};
let lang = document.documentElement.getAttribute('data-lang') === 'cn' ? 'cn' : 'en';
let I18N = I18N_ALL[lang] || I18N_ALL.en;
let DATASETS = window.__GAI_HISTORY_DATASETS__ || {{ all: {{}}, projects: [], by_project: {{}}, default_project: '__all__' }};
let A = DATASETS.all || {{}};
let currentProject = DATASETS.default_project || '__all__';
let currentTrend = (A.default_trend || 'today');
let chartHandles = [];
const TABLE_PAGE_SIZE = 25;
let tablePage = 0;

function themeColors() {{
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? ['#0284c7', '#0f766e', '#7c3aed', '#d97706', '#db2777', '#2563eb', '#e11d48', '#0d9488']
    : ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#fb7185', '#2dd4bf'];
}}

function ink() {{
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#e8eef8';
}}
function muted() {{
  return getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#94a3b8';
}}

function showToast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.remove('show'), 1600);
}}

function esc(s) {{
  return String(s)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}}

function activeSlice() {{
  if (currentProject === '__all__') return DATASETS.all || {{}};
  return (DATASETS.by_project && DATASETS.by_project[currentProject]) || {{}};
}}

function applyViewScope() {{
  const isAll = currentProject === '__all__';
  document.documentElement.classList.toggle('view-all', isAll);
  document.documentElement.classList.toggle('view-repo', !isAll);
  const hint = document.getElementById('project-hint');
  if (hint) hint.textContent = isAll ? I18N.hint_project_all : I18N.hint_project_repo;
}}

function updateMetaLine() {{
  const el = document.getElementById('meta-line');
  if (!el) return;
  const src = A.source || '';
  const gen = A.generated_at || '';
  el.textContent = (I18N.generated + ': ' + gen + ' · ' + I18N.source + ': ' + src);
}}

function updateKpis() {{
  const totals = A.totals || {{}};
  const setText = (id, value) => {{
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }};
  setText('kpi-calls', totals.calls || 0);
  setText('kpi-ok', totals.ok || 0);
  setText('kpi-fail', totals.fail || 0);
  setText('kpi-ms', totals.avg_duration_ms == null ? '—' : (totals.avg_duration_ms + ' ms'));
}}

function disposeCharts() {{
  chartHandles.forEach(c => {{ try {{ c.dispose(); }} catch (e) {{}} }});
  chartHandles = [];
}}

function makeChart(id) {{
  const el = document.getElementById(id);
  if (!el || typeof echarts === 'undefined') return null;
  const c = echarts.init(el);
  chartHandles.push(c);
  return c;
}}

function barOption(labels, values, color) {{
  return {{
    textStyle: {{ color: ink() }},
    grid: {{ left: 12, right: 18, top: 18, bottom: 8, containLabel: true }},
    tooltip: {{ trigger: 'axis' }},
    xAxis: {{ type: 'value', axisLabel: {{ color: muted() }}, splitLine: {{ lineStyle: {{ color: 'rgba(148,163,184,.2)' }} }} }},
    yAxis: {{
      type: 'category', data: labels.slice().reverse(),
      axisLabel: {{ color: muted() }}, axisLine: {{ lineStyle: {{ color: muted() }} }}
    }},
    series: [{{
      type: 'bar', data: values.slice().reverse(),
      itemStyle: {{ color: color || themeColors()[0], borderRadius: [0, 6, 6, 0] }},
      label: {{ show: true, position: 'right', color: muted() }}
    }}]
  }};
}}

function pieOption(labels, values) {{
  const colors = themeColors();
  return {{
    textStyle: {{ color: ink() }},
    tooltip: {{ trigger: 'item' }},
    legend: {{ bottom: 0, textStyle: {{ color: muted() }} }},
    series: [{{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '46%'],
      data: labels.map((name, i) => ({{ name, value: values[i] || 0 }})),
      itemStyle: {{ borderRadius: 6 }},
      label: {{ color: muted() }},
      color: colors
    }}]
  }};
}}

function initTrend() {{
  const trends = A.trends || {{}};
  const pack = trends[currentTrend] || trends.today || {{ labels: [], calls: [] }};
  const titleKey = pack.title_key;
  const hint = document.getElementById('trend-hint');
  if (hint && titleKey && I18N[titleKey]) hint.textContent = I18N[titleKey];
  document.querySelectorAll('#trend-seg button').forEach(btn => {{
    btn.classList.toggle('active', btn.getAttribute('data-mode') === currentTrend);
  }});
  const c = makeChart('chart-trend');
  if (!c) return;
  c.setOption({{
    textStyle: {{ color: ink() }},
    grid: {{ left: 12, right: 18, top: 28, bottom: 8, containLabel: true }},
    tooltip: {{ trigger: 'axis' }},
    xAxis: {{
      type: 'category', data: pack.labels || [],
      axisLabel: {{ color: muted() }}, axisLine: {{ lineStyle: {{ color: muted() }} }}
    }},
    yAxis: {{
      type: 'value', name: I18N.calls, nameTextStyle: {{ color: muted() }},
      axisLabel: {{ color: muted() }}, splitLine: {{ lineStyle: {{ color: 'rgba(148,163,184,.2)' }} }}
    }},
    series: [{{
      type: 'line', smooth: true, data: pack.calls || [],
      areaStyle: {{ opacity: .18 }},
      itemStyle: {{ color: themeColors()[0] }},
      lineStyle: {{ width: 2 }}
    }}]
  }});
}}

function initHeatmapRepo() {{
  const heat = A.heatmap_repo || {{}};
  const repos = heat.repos || [];
  const commands = heat.commands || [];
  const data = heat.data || [];
  const c = makeChart('chart-heat-repo');
  if (!c) return;
  const max = data.reduce((m, d) => Math.max(m, d[2] || 0), 0) || 1;
  c.setOption({{
    textStyle: {{ color: ink() }},
    tooltip: {{
      formatter: (p) => {{
        const d = p.data || [];
        return (commands[d[0]] || '') + ' × ' + (repos[d[1]] || '') + ': ' + (d[2] || 0);
      }}
    }},
    grid: {{ left: 12, right: 24, top: 16, bottom: 8, containLabel: true }},
    xAxis: {{ type: 'category', data: commands, axisLabel: {{ color: muted(), rotate: 30 }} }},
    yAxis: {{ type: 'category', data: repos, axisLabel: {{ color: muted() }} }},
    visualMap: {{
      min: 0, max: max, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
      textStyle: {{ color: muted() }},
      inRange: {{ color: document.documentElement.getAttribute('data-theme') === 'light'
        ? ['#e0f2fe', '#0284c7'] : ['#0b1220', '#38bdf8'] }}
    }},
    series: [{{
      type: 'heatmap', data: data,
      label: {{ show: true, color: muted(), fontSize: 10 }}
    }}]
  }});
}}

function recentRows() {{ return A.recent || []; }}

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
    const cmd = r.subcommand ? (r.command + ' ' + r.subcommand) : (r.command || '—');
    const argv = Array.isArray(r.argv) ? r.argv.join(' ') : (r.argv || '—');
    const status = r.ok
      ? '<span class="pill ok">OK</span>'
      : ('<span class="pill fail">FAIL(' + esc(String(r.exit_code ?? '')) + ')</span>');
    tr.innerHTML =
      '<td>' + esc(r.ts || '') + '</td>' +
      '<td>' + esc(who) + '</td>' +
      '<td>' + esc(r.repo_name || '—') + '</td>' +
      '<td>' + esc(cmd) + '</td>' +
      '<td>' + esc(argv) + '</td>' +
      '<td>' + status + '</td>' +
      '<td>' + esc(r.duration_ms != null ? String(r.duration_ms) : '—') + '</td>';
    body.appendChild(tr);
  }}
  const metaEl = document.getElementById('pager-meta');
  const prev = document.getElementById('btn-page-prev');
  const next = document.getElementById('btn-page-next');
  if (metaEl) {{
    const shown = rows.length ? `${{start + 1}}–${{start + slice.length}} / ${{rows.length}}` : '0 / 0';
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
  const headers = ['ts','git_user','git_email','repo_name','command','subcommand','argv','exit_code','ok','duration_ms'];
  const escapeCell = (v) => {{
    const s = v == null ? '' : (Array.isArray(v) ? v.join(' ') : String(v));
    if (/[",\\n\\r]/.test(s)) return '"' + s.replaceAll('"', '""') + '"';
    return s;
  }};
  const lines = [headers.join(',')];
  for (const r of rows) lines.push(headers.map((h) => escapeCell(r[h])).join(','));
  const blob = new Blob([lines.join('\\n')], {{ type: 'text/csv;charset=utf-8' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'gai-history.csv';
  a.click();
  URL.revokeObjectURL(a.href);
  showToast(I18N.export_ok || 'CSV exported');
}}

function renderDashboard() {{
  A = activeSlice();
  applyViewScope();
  updateMetaLine();
  updateKpis();
  disposeCharts();
  if (!(A.totals && A.totals.calls)) {{
    // still render empty charts
  }}
  initTrend();
  const cmd = A.by_command || {{}};
  const c1 = makeChart('chart-command');
  if (c1) c1.setOption(barOption(cmd.labels || [], cmd.calls || [], themeColors()[0]));
  const st = A.by_status || {{}};
  const labels = (st.labels || []).map((x) => x === 'ok' ? I18N.ok : (x === 'fail' ? I18N.fail : x));
  const c2 = makeChart('chart-status');
  if (c2) c2.setOption(pieOption(labels, st.calls || []));
  const user = A.by_user || {{}};
  const c3 = makeChart('chart-user');
  if (c3) c3.setOption(barOption(user.labels || [], user.calls || [], themeColors()[2]));
  const dur = A.duration_by_command || {{}};
  const c4 = makeChart('chart-duration');
  if (c4) c4.setOption(barOption(dur.labels || [], dur.avg_ms || [], themeColors()[3]));
  if (currentProject === '__all__') {{
    const repo = A.by_repo || {{}};
    const c5 = makeChart('chart-repo');
    if (c5) c5.setOption(barOption(repo.labels || [], repo.calls || [], themeColors()[1]));
    initHeatmapRepo();
  }}
  fillTable();
}}

let dropdownBound = false;

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
  DATASETS = next || window.__GAI_HISTORY_DATASETS__ || DATASETS;
  window.__GAI_HISTORY_DATASETS__ = DATASETS;
  A = DATASETS.all || {{}};
  if (!currentTrend) currentTrend = A.default_trend || 'today';
  tablePage = 0;
  rebuildProjectMenu();
  updateMetaLine();
  renderDashboard();
}}

function refreshHint() {{
  const viaHttp = location.protocol === 'http:' || location.protocol === 'https:';
  return viaHttp
    ? (I18N.refresh_fail_http || I18N.refresh_fail || 'Failed')
    : (I18N.refresh_fail_file || I18N.refresh_fail || 'Failed');
}}

function refreshData() {{
  const btn = document.getElementById('btn-refresh');
  if (btn) {{ btn.disabled = true; btn.textContent = I18N.refreshing || '...'; }}
  const old = document.getElementById('history-data-loader');
  if (old) old.remove();
  const s = document.createElement('script');
  s.id = 'history-data-loader';
  s.src = 'history-data.js?t=' + Date.now();
  s.onload = () => {{
    applyDatasets(window.__GAI_HISTORY_DATASETS__);
    showToast(I18N.refresh_ok || 'OK');
    if (btn) {{ btn.disabled = false; btn.textContent = I18N.refresh; }}
  }};
  s.onerror = () => {{
    showToast(refreshHint());
    if (btn) {{ btn.disabled = false; btn.textContent = I18N.refresh; }}
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
  if (theme === currentTheme()) {{ applyTheme(theme); renderDashboard(); return; }}
  const run = () => {{ applyTheme(theme); renderDashboard(); }};
  if (animate !== false && document.startViewTransition &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{
    document.startViewTransition(run);
    return;
  }}
  run();
}}

function applyStaticI18n() {{
  document.querySelectorAll('[data-i]').forEach((el) => {{
    const key = el.getAttribute('data-i');
    const val = I18N[key];
    if (typeof val === 'string') el.textContent = val;
  }});
  document.title = I18N.title || document.title;
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
  document.getElementById('btn-page-prev').addEventListener('click', () => {{ tablePage -= 1; fillTable(); }});
  document.getElementById('btn-page-next').addEventListener('click', () => {{ tablePage += 1; fillTable(); }});
  document.getElementById('btn-theme-light').addEventListener('click', () => setTheme('light'));
  document.getElementById('btn-theme-dark').addEventListener('click', () => setTheme('dark'));
  document.getElementById('btn-lang-cn').addEventListener('click', () => setLang('cn'));
  document.getElementById('btn-lang-en').addEventListener('click', () => setLang('en'));
  document.querySelectorAll('#trend-seg button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      currentTrend = btn.getAttribute('data-mode') || 'today';
      renderDashboard();
    }});
  }});
  setTheme(currentTheme(), false);
  setLang(lang);
  initProjectDropdown();
  applyDatasets(window.__GAI_HISTORY_DATASETS__);
  window.addEventListener('resize', () => chartHandles.forEach(c => c.resize()));
  requestAnimationFrame(() => document.documentElement.classList.add('theme-ready'));
}})();
</script>
</body>
</html>
"""
