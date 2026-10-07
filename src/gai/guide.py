"""Generate a local HTML usage guide under ``.gai/guide.html`` (bilingual)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gai.llm.history import project_root
from gai.llm.usage_report import path_to_file_url

_GUIDE_RELATIVE = Path(".gai") / "guide.html"

# Re-export for callers that only need the URL helper via guide.
__all__ = [
    "guide_path",
    "path_to_file_url",
    "write_guide_html",
]


def guide_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _GUIDE_RELATIVE


def _commands() -> list[dict[str, Any]]:
    """Structured command cards for the HTML (en + cn)."""
    return [
        {
            "id": "add",
            "name": "add",
            "en": {
                "title": "Stage files",
                "blurb": "Wrapper around git add. Defaults to '.' when no path is given.",
                "examples": [
                    ("gai add", "Stage all changes in the current directory"),
                    ("gai add src/", "Stage files under src/"),
                    ("gai add --cn -t", "Chinese tips + print git trace"),
                ],
            },
            "cn": {
                "title": "暂存文件",
                "blurb": "包装 git add。未指定路径时默认暂存当前目录。",
                "examples": [
                    ("gai add", "暂存当前目录全部变更"),
                    ("gai add src/", "暂存 src/ 目录下的文件"),
                    ("gai add --cn -t", "中文提示暂存，并打印 git 链路"),
                ],
            },
        },
        {
            "id": "unadd",
            "name": "unadd",
            "en": {
                "title": "Unstage files",
                "blurb": "Undo staging. Asks for confirmation.",
                "examples": [
                    ("gai unadd --cn", "Unstage all staged files"),
                    ("gai unadd src/", "Unstage files under src/"),
                ],
            },
            "cn": {
                "title": "撤销暂存",
                "blurb": "撤销暂存区文件，需确认。",
                "examples": [
                    ("gai unadd --cn", "撤销全部暂存"),
                    ("gai unadd src/", "撤销 src/ 下的暂存"),
                ],
            },
        },
        {
            "id": "uncommit",
            "name": "uncommit",
            "en": {
                "title": "Undo latest commit",
                "blurb": "Soft reset (git reset --soft HEAD~1); changes stay staged.",
                "examples": [
                    ("gai uncommit --cn", "Soft-undo the latest commit"),
                ],
            },
            "cn": {
                "title": "撤销最近提交",
                "blurb": "软撤销（git reset --soft HEAD~1）；改动仍保留在暂存区。",
                "examples": [
                    ("gai uncommit --cn", "软撤销最近一次提交"),
                ],
            },
        },
        {
            "id": "review",
            "name": "review",
            "en": {
                "title": "AI code review",
                "blurb": "Review staged changes only — no commit.",
                "examples": [
                    ("gai review --cn", "AI-review staged changes"),
                    ("gai review --json", "Output review as JSON"),
                ],
            },
            "cn": {
                "title": "AI 代码审查",
                "blurb": "只审查已暂存变更，不提交。",
                "examples": [
                    ("gai review --cn", "审查已暂存变更"),
                    ("gai review --json", "以 JSON 输出审查结果"),
                ],
            },
        },
        {
            "id": "commit",
            "name": "commit",
            "en": {
                "title": "Review & commit",
                "blurb": "Review → suggest Conventional Commit message → confirm → commit.",
                "examples": [
                    ("gai commit --cn", "Full interactive flow"),
                    ("gai commit -y --cn", "Skip confirmations"),
                    ("gai commit --cn --push", "Commit then push"),
                    ('gai commit -m "fix: handle nil" --no-ai', "Manual message, skip AI"),
                ],
            },
            "cn": {
                "title": "审查并提交",
                "blurb": "审查 → 建议 Conventional Commits 信息 → 确认 → 提交。",
                "examples": [
                    ("gai commit --cn", "完整交互流程"),
                    ("gai commit -y --cn", "跳过交互确认"),
                    ("gai commit --cn --push", "提交成功后推送"),
                    ('gai commit -m "fix: handle nil" --no-ai', "指定信息并跳过 AI"),
                ],
            },
        },
        {
            "id": "push",
            "name": "push",
            "en": {
                "title": "Push branch",
                "blurb": "Push current branch; warns when there is nothing to push.",
                "examples": [
                    ("gai push --cn", "Push after checks"),
                    ("gai push -y --cn", "Push without confirm"),
                    ("gai push -r origin -u --cn", "Push to origin and set upstream"),
                ],
            },
            "cn": {
                "title": "推送分支",
                "blurb": "推送当前分支；无可推送内容时会提示，不当成成功。",
                "examples": [
                    ("gai push --cn", "检查后推送"),
                    ("gai push -y --cn", "跳过确认直接推送"),
                    ("gai push -r origin -u --cn", "推送到 origin 并设置上游"),
                ],
            },
        },
        {
            "id": "pull",
            "name": "pull",
            "en": {
                "title": "Pull updates",
                "blurb": "Check remote updates, then pull (merge or rebase).",
                "examples": [
                    ("gai pull --cn", "Confirm then pull"),
                    ("gai pull -y --cn", "Pull without confirm"),
                    ("gai pull --rebase --cn", "Pull with rebase"),
                ],
            },
            "cn": {
                "title": "拉取更新",
                "blurb": "检查远程有更新后确认再拉取（merge 或 rebase）。",
                "examples": [
                    ("gai pull --cn", "确认后拉取"),
                    ("gai pull -y --cn", "跳过确认直接拉取"),
                    ("gai pull --rebase --cn", "用 rebase 拉取"),
                ],
            },
        },
        {
            "id": "report",
            "name": "report",
            "en": {
                "title": "Work summary",
                "blurb": "Turn recent commits into a paste-ready work report.",
                "examples": [
                    ("gai report --cn", "Default recent window"),
                    ("gai report --since 7d --cn", "Last 7 days"),
                    (
                        "gai report --since 2026-09-01 --until 2026-09-20 --cn",
                        "Explicit date range",
                    ),
                    ("gai report --alltime --author me --cn", "Full history for current git user"),
                ],
            },
            "cn": {
                "title": "工作总结",
                "blurb": "根据近期提交生成可粘贴的工作总结（周报 / 日报）。",
                "examples": [
                    ("gai report --cn", "默认时间窗口"),
                    ("gai report --since 7d --cn", "最近 7 天"),
                    (
                        "gai report --since 2026-09-01 --until 2026-09-20 --cn",
                        "指定起止日期",
                    ),
                    ("gai report --alltime --author me --cn", "当前用户全部历史"),
                ],
            },
        },
        {
            "id": "usage",
            "name": "usage",
            "en": {
                "title": "Token usage",
                "blurb": "Local LLM token history (JSONL) and optional ECharts dashboard.",
                "examples": [
                    ("gai usage --cn", "Show recent usage table"),
                    ("gai usage --report --cn", "Sync .gai/usage-report.html"),
                    ("gai usage --since 7d --group action --cn", "Last 7 days by action"),
                ],
            },
            "cn": {
                "title": "Token 用量",
                "blurb": "本地大模型 token 用量（JSONL），可生成 ECharts 可视化报告。",
                "examples": [
                    ("gai usage --cn", "查看近期用量表"),
                    ("gai usage --report --cn", "同步 .gai/usage-report.html"),
                    ("gai usage --since 7d --group action --cn", "最近 7 天并按动作汇总"),
                ],
            },
        },
        {
            "id": "balance",
            "name": "balance",
            "en": {
                "title": "API balance",
                "blurb": "Query remaining credit when the provider supports it.",
                "examples": [
                    ("gai balance --cn", "Query balance (Chinese)"),
                    ("gai balance", "Query balance (English)"),
                ],
            },
            "cn": {
                "title": "余额查询",
                "blurb": "查询 API Key 剩余额度（若厂商提供接口）。",
                "examples": [
                    ("gai balance --cn", "中文输出余额"),
                    ("gai balance", "英文输出余额"),
                ],
            },
        },
        {
            "id": "config",
            "name": "config",
            "en": {
                "title": "Configuration",
                "blurb": "View or update ~/.gai/config.toml (env vars still win).",
                "examples": [
                    ("gai config --show --cn", "Show effective config (secrets masked)"),
                    (
                        "gai config --api-key <key> --base-url <url> --model <name>",
                        "Save API settings",
                    ),
                ],
            },
            "cn": {
                "title": "配置",
                "blurb": "查看或更新 ~/.gai/config.toml（环境变量优先级更高）。",
                "examples": [
                    ("gai config --show --cn", "查看生效配置（密钥已掩码）"),
                    (
                        "gai config --api-key <key> --base-url <url> --model <name>",
                        "写入 API 配置",
                    ),
                ],
            },
        },
        {
            "id": "completion",
            "name": "completion",
            "en": {
                "title": "Tab completion",
                "blurb": "Install shell Tab-completion for gai subcommands and options.",
                "examples": [
                    ("gai completion install --shell powershell --cn", "Install for PowerShell"),
                    ("gai completion install --cn", "Auto-detect shell"),
                    ("gai completion show --shell powershell", "Print script only"),
                ],
            },
            "cn": {
                "title": "Tab 自动补全",
                "blurb": "为 gai 子命令与选项安装 shell Tab 补全。",
                "examples": [
                    ("gai completion install --shell powershell --cn", "安装 PowerShell 补全"),
                    ("gai completion install --cn", "自动检测 shell"),
                    ("gai completion show --shell powershell", "仅打印脚本"),
                ],
            },
        },
        {
            "id": "guide",
            "name": "guide",
            "en": {
                "title": "This guide",
                "blurb": "Regenerate this HTML page under .gai/guide.html.",
                "examples": [
                    ("gai guide --cn", "Generate and open Chinese-first page"),
                    ("gai guide", "Generate and open English-first page"),
                ],
            },
            "cn": {
                "title": "本教程页",
                "blurb": "重新生成 .gai/guide.html 可视化教程。",
                "examples": [
                    ("gai guide --cn", "生成并以中文为首屏语言"),
                    ("gai guide", "生成并以英文为首屏语言"),
                ],
            },
        },
    ]


def _i18n() -> dict[str, dict[str, str]]:
    return {
        "cn": {
            "doc_title": "gai 使用指南",
            "brand": "gai",
            "tagline": "本地 Git 提交与代码审查 Agent",
            "lang_cn": "中文",
            "lang_en": "EN",
            "nav_overview": "概览",
            "nav_flow": "日常流程",
            "nav_setup": "安装与配置",
            "nav_commands": "命令一览",
            "nav_tips": "提示与约定",
            "overview_h": "这是什么？",
            "overview_p": (
                "gai 是一个本地 CLI：对已暂存（staged）变更做 AI Code Review、"
                "生成 Conventional Commits 提交信息；可推送 / 拉取远程；"
                "还可根据提交记录生成工作总结。必须在 git 仓库目录下使用。"
            ),
            "flow_h": "推荐日常流程",
            "flow_steps": [
                "gai add — 暂存改动",
                "gai review --cn — 先审查（可选）",
                "gai commit --cn — 审查 → 建议 Message → 确认 → 提交",
                "gai push --cn — 推送到远程（或 commit 时加 --push）",
                "gai report --cn — 需要时生成工作总结",
            ],
            "setup_h": "安装与配置",
            "setup_install": "安装（开发模式）",
            "setup_config": "配置优先级：环境变量 > ~/.gai/config.toml > 默认值",
            "setup_keys": (
                "常用环境变量：GAI_API_KEY / OPENAI_API_KEY、GAI_BASE_URL、GAI_MODEL。"
                "也可用 gai config --api-key … 写入配置文件。"
            ),
            "setup_cn": "几乎所有命令支持 --cn：中文运行时文案；与 -h 联用显示中文帮助。",
            "commands_h": "命令一览",
            "commands_hint": "点击左侧或下方卡片查看示例。示例可点击复制。",
            "examples_h": "示例",
            "copied": "已复制",
            "tips_h": "提示与约定",
            "tips": [
                "审查 / 提交只看 staged diff（git diff --cached），不会偷偷提交未暂存文件。",
                "不拦截原生 git：也可用 --no-ai -m 或直接 git commit / git push。",
                "用量报告：gai usage --report → .gai/usage-report.html",
                "本教程：gai guide [--cn] → .gai/guide.html（再次运行会覆盖同步）",
                "PowerShell Tab 补全：gai completion install --shell powershell --cn，然后重开终端",
            ],
            "footer": "由 gai guide 生成 · 存放于仓库 .gai/guide.html · 页面内可随时切换中/英",
            "generated": "生成时间",
        },
        "en": {
            "doc_title": "gai User Guide",
            "brand": "gai",
            "tagline": "Local Git commit & code review agent",
            "lang_cn": "中文",
            "lang_en": "EN",
            "nav_overview": "Overview",
            "nav_flow": "Daily flow",
            "nav_setup": "Setup",
            "nav_commands": "Commands",
            "nav_tips": "Tips",
            "overview_h": "What is gai?",
            "overview_p": (
                "gai is a local CLI that AI-reviews staged changes, suggests Conventional "
                "Commits messages, can push/pull remotes, and can turn commit history into "
                "a work summary. Run it inside a git repository."
            ),
            "flow_h": "Recommended daily flow",
            "flow_steps": [
                "gai add — stage changes",
                "gai review --cn — optional review-only pass",
                "gai commit --cn — review → suggest message → confirm → commit",
                "gai push --cn — push (or pass --push on commit)",
                "gai report --cn — work summary when you need it",
            ],
            "setup_h": "Install & configure",
            "setup_install": "Install (editable)",
            "setup_config": "Config priority: env vars > ~/.gai/config.toml > defaults",
            "setup_keys": (
                "Common env vars: GAI_API_KEY / OPENAI_API_KEY, GAI_BASE_URL, GAI_MODEL. "
                "Or save via gai config --api-key …"
            ),
            "setup_cn": (
                "Most commands accept --cn for Chinese runtime text; "
                "combine with -h for Chinese help."
            ),
            "commands_h": "Commands",
            "commands_hint": "Use the nav or cards below. Click an example to copy.",
            "examples_h": "Examples",
            "copied": "Copied",
            "tips_h": "Tips & conventions",
            "tips": [
                "Review/commit only look at staged diffs (git diff --cached).",
                "Native git stays available: use --no-ai -m or plain git commit / git push.",
                "Usage dashboard: gai usage --report → .gai/usage-report.html",
                "This guide: gai guide [--cn] → .gai/guide.html (re-run overwrites)",
                "PowerShell Tab completion: gai completion install --shell powershell --cn, then restart the terminal",
            ],
            "footer": "Generated by gai guide · stored at .gai/guide.html · switch language anytime",
            "generated": "Generated",
        },
    }


def write_guide_html(
    *,
    chinese: bool = False,
    path: Path | None = None,
) -> Path:
    """Write bilingual guide HTML. ``chinese`` sets the initial language."""
    target = path or guide_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    initial = "cn" if chinese else "en"
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    payload = {
        "initialLang": initial,
        "generated": generated,
        "i18n": _i18n(),
        "commands": _commands(),
    }
    html = _render_html(payload)
    target.write_text(html, encoding="utf-8")
    return target


def _render_html(payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    # Escape </script> in JSON for HTML embedding safety.
    data_json = data_json.replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en" data-lang="{payload["initialLang"]}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gai guide</title>
  <style>
    :root {{
      --bg0: #0b1220;
      --bg1: #121a2b;
      --panel: linear-gradient(165deg, rgba(36, 48, 72, .96), rgba(18, 28, 46, .96));
      --border: rgba(148, 163, 184, 0.22);
      --text: #e8eef9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent2: #a78bfa;
      --ok: #4ade80;
      --shadow: 0 10px 28px rgba(0,0,0,.35), 0 1px 0 rgba(255,255,255,.06) inset;
      --radius: 16px;
      --font: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, "Cascadia Code", "Consolas", monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; min-height: 100%; }}
    body {{
      font-family: var(--font);
      color: var(--text);
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(56,189,248,.18), transparent 55%),
        radial-gradient(900px 500px at 90% 0%, rgba(167,139,250,.14), transparent 50%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{
      display: grid;
      grid-template-columns: 240px minmax(0, 1fr);
      gap: 0;
      max-width: 1180px;
      margin: 0 auto;
      min-height: 100vh;
    }}
    .side {{
      position: sticky;
      top: 0;
      align-self: start;
      height: 100vh;
      padding: 22px 16px;
      border-right: 1px solid var(--border);
      background: rgba(10, 16, 28, .55);
      backdrop-filter: blur(10px);
      overflow: auto;
    }}
    .brand {{
      font-size: 1.55rem;
      font-weight: 780;
      letter-spacing: -.03em;
      background: linear-gradient(90deg, #e0f2fe, #c4b5fd);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }}
    .tagline {{
      margin: 6px 0 16px;
      color: var(--muted);
      font-size: .82rem;
      line-height: 1.4;
    }}
    .lang {{
      display: inline-flex;
      gap: 4px;
      padding: 4px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, .7);
      margin-bottom: 18px;
    }}
    .lang button {{
      border: 0;
      background: transparent;
      color: var(--muted);
      padding: 6px 12px;
      border-radius: 999px;
      cursor: pointer;
      font-size: .8rem;
      font-weight: 600;
    }}
    .lang button.active {{
      background: linear-gradient(180deg, rgba(56,189,248,.28), rgba(56,189,248,.1));
      color: #bae6fd;
      box-shadow: 0 0 0 1px rgba(56,189,248,.35) inset;
    }}
    .nav {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .nav a {{
      color: #cbd5e1;
      padding: 8px 10px;
      border-radius: 10px;
      font-size: .88rem;
      text-decoration: none;
    }}
    .nav a:hover, .nav a.active {{
      background: rgba(56,189,248,.12);
      color: #e0f2fe;
      text-decoration: none;
    }}
    .nav .cmd {{
      font-family: var(--mono);
      font-size: .78rem;
      color: #93c5fd;
      padding-left: 18px;
    }}
    .main {{
      padding: 28px 28px 48px;
    }}
    .hero {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 22px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 1.65rem;
      font-weight: 760;
      letter-spacing: -.02em;
    }}
    .meta {{
      color: var(--muted);
      font-size: .78rem;
      align-self: center;
    }}
    section {{
      margin-bottom: 28px;
      scroll-margin-top: 20px;
    }}
    .card {{
      position: relative;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px 18px 16px;
      margin-bottom: 12px;
    }}
    .card h2 {{
      margin: 0 0 8px;
      font-size: 1.05rem;
    }}
    .card p, .blurb {{
      margin: 0;
      color: var(--muted);
      font-size: .9rem;
      line-height: 1.55;
    }}
    ol.flow {{
      margin: 10px 0 0;
      padding-left: 1.2rem;
      color: #e2e8f0;
      line-height: 1.7;
      font-size: .92rem;
    }}
    pre.install {{
      margin: 12px 0 0;
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(2, 8, 20, .55);
      border: 1px solid rgba(148,163,184,.18);
      overflow: auto;
      font-family: var(--mono);
      font-size: .82rem;
      color: #bae6fd;
    }}
    .cmd-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }}
    .cmd-card {{
      cursor: pointer;
      transition: transform .15s ease, border-color .15s ease;
    }}
    .cmd-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(56,189,248,.45);
    }}
    .cmd-card .name {{
      font-family: var(--mono);
      font-size: .95rem;
      font-weight: 700;
      color: #7dd3fc;
    }}
    .cmd-card .title {{
      margin-top: 4px;
      font-weight: 650;
    }}
    .detail {{
      display: none;
    }}
    .detail.open {{ display: block; }}
    .examples {{
      margin: 12px 0 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .ex {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(2, 8, 20, .45);
      border: 1px solid rgba(148,163,184,.16);
      cursor: pointer;
    }}
    .ex:hover {{ border-color: rgba(56,189,248,.4); }}
    .ex code {{
      font-family: var(--mono);
      font-size: .82rem;
      color: #bae6fd;
      word-break: break-all;
    }}
    .ex .desc {{
      color: var(--muted);
      font-size: .8rem;
    }}
    .hint {{
      color: var(--muted);
      font-size: .8rem;
      margin: 0 0 12px;
    }}
    ul.tips {{
      margin: 8px 0 0;
      padding-left: 1.15rem;
      color: #e2e8f0;
      line-height: 1.7;
      font-size: .9rem;
    }}
    footer {{
      margin-top: 28px;
      color: var(--muted);
      font-size: .78rem;
      border-top: 1px solid var(--border);
      padding-top: 14px;
    }}
    .toast {{
      position: fixed;
      bottom: 22px;
      right: 22px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(34, 197, 94, .92);
      color: #052e16;
      font-weight: 700;
      font-size: .85rem;
      opacity: 0;
      pointer-events: none;
      transition: opacity .2s ease;
      box-shadow: 0 8px 24px rgba(0,0,0,.35);
    }}
    .toast.show {{ opacity: 1; }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .side {{
        position: relative;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }}
      .nav {{ flex-direction: row; flex-wrap: wrap; }}
      .nav .cmd {{ display: none; }}
      .ex {{ grid-template-columns: 1fr; }}
      .main {{ padding: 18px 16px 40px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="side">
      <div class="brand" data-i="brand">gai</div>
      <div class="tagline" data-i="tagline"></div>
      <div class="lang" role="group" aria-label="Language">
        <button type="button" id="btn-cn" data-lang="cn">中文</button>
        <button type="button" id="btn-en" data-lang="en">EN</button>
      </div>
      <nav class="nav" id="side-nav">
        <a href="#overview" data-i="nav_overview"></a>
        <a href="#flow" data-i="nav_flow"></a>
        <a href="#setup" data-i="nav_setup"></a>
        <a href="#commands" data-i="nav_commands"></a>
        <div id="cmd-nav"></div>
        <a href="#tips" data-i="nav_tips"></a>
      </nav>
    </aside>
    <main class="main">
      <div class="hero">
        <h1 data-i="doc_title"></h1>
        <div class="meta"><span data-i="generated"></span>: <span id="gen-time"></span></div>
      </div>

      <section id="overview" class="card">
        <h2 data-i="overview_h"></h2>
        <p data-i="overview_p"></p>
      </section>

      <section id="flow" class="card">
        <h2 data-i="flow_h"></h2>
        <ol class="flow" id="flow-list"></ol>
      </section>

      <section id="setup" class="card">
        <h2 data-i="setup_h"></h2>
        <p class="blurb" data-i="setup_install"></p>
        <pre class="install">python -m pip install -e ".[dev]"
gai --version
gai config --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat</pre>
        <p class="blurb" style="margin-top:12px" data-i="setup_config"></p>
        <p class="blurb" style="margin-top:8px" data-i="setup_keys"></p>
        <p class="blurb" style="margin-top:8px" data-i="setup_cn"></p>
      </section>

      <section id="commands">
        <h2 data-i="commands_h" style="margin:0 0 6px;font-size:1.05rem"></h2>
        <p class="hint" data-i="commands_hint"></p>
        <div class="cmd-grid" id="cmd-grid"></div>
        <div class="card detail" id="cmd-detail">
          <h2 id="detail-title"></h2>
          <p class="blurb" id="detail-blurb"></p>
          <h3 style="margin:14px 0 0;font-size:.92rem" data-i="examples_h"></h3>
          <div class="examples" id="detail-examples"></div>
        </div>
      </section>

      <section id="tips" class="card">
        <h2 data-i="tips_h"></h2>
        <ul class="tips" id="tips-list"></ul>
      </section>

      <footer data-i="footer"></footer>
    </main>
  </div>
  <div class="toast" id="toast"></div>
  <script id="guide-data" type="application/json">{data_json}</script>
  <script>
(function () {{
  const DATA = JSON.parse(document.getElementById('guide-data').textContent);
  let lang = DATA.initialLang === 'cn' ? 'cn' : 'en';
  const toast = document.getElementById('toast');
  let toastTimer = null;

  function t() {{ return DATA.i18n[lang]; }}

  function showToast(msg) {{
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 1200);
  }}

  function copyText(text) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      return navigator.clipboard.writeText(text);
    }}
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    return Promise.resolve();
  }}

  function setLang(next) {{
    lang = next === 'cn' ? 'cn' : 'en';
    document.documentElement.setAttribute('data-lang', lang);
    document.documentElement.lang = lang === 'cn' ? 'zh-CN' : 'en';
    document.getElementById('btn-cn').classList.toggle('active', lang === 'cn');
    document.getElementById('btn-en').classList.toggle('active', lang === 'en');
    document.title = t().doc_title;
    document.querySelectorAll('[data-i]').forEach((el) => {{
      const key = el.getAttribute('data-i');
      const val = t()[key];
      if (typeof val === 'string') el.textContent = val;
    }});
    document.getElementById('gen-time').textContent = DATA.generated;

    const flow = document.getElementById('flow-list');
    flow.innerHTML = '';
    (t().flow_steps || []).forEach((step) => {{
      const li = document.createElement('li');
      li.textContent = step;
      flow.appendChild(li);
    }});

    const tips = document.getElementById('tips-list');
    tips.innerHTML = '';
    (t().tips || []).forEach((tip) => {{
      const li = document.createElement('li');
      li.textContent = tip;
      tips.appendChild(li);
    }});

    renderCommands();
    const openId = document.getElementById('cmd-detail').dataset.openId;
    if (openId) openCommand(openId, false);
  }}

  function cmdLocale(cmd) {{
    return lang === 'cn' ? cmd.cn : cmd.en;
  }}

  function renderCommands() {{
    const grid = document.getElementById('cmd-grid');
    const nav = document.getElementById('cmd-nav');
    grid.innerHTML = '';
    nav.innerHTML = '';
    DATA.commands.forEach((cmd) => {{
      const loc = cmdLocale(cmd);
      const card = document.createElement('div');
      card.className = 'card cmd-card';
      card.innerHTML =
        '<div class="name">gai ' + cmd.name + '</div>' +
        '<div class="title">' + loc.title + '</div>' +
        '<p class="blurb" style="margin-top:6px">' + loc.blurb + '</p>';
      card.addEventListener('click', () => openCommand(cmd.id, true));
      grid.appendChild(card);

      const a = document.createElement('a');
      a.href = '#' + cmd.id;
      a.className = 'cmd';
      a.textContent = cmd.name;
      a.addEventListener('click', (e) => {{
        e.preventDefault();
        openCommand(cmd.id, true);
      }});
      nav.appendChild(a);
    }});
  }}

  function openCommand(id, scroll) {{
    const cmd = DATA.commands.find((c) => c.id === id);
    if (!cmd) return;
    const loc = cmdLocale(cmd);
    const detail = document.getElementById('cmd-detail');
    detail.classList.add('open');
    detail.dataset.openId = id;
    document.getElementById('detail-title').textContent = 'gai ' + cmd.name + ' — ' + loc.title;
    document.getElementById('detail-blurb').textContent = loc.blurb;
    const box = document.getElementById('detail-examples');
    box.innerHTML = '';
    (loc.examples || []).forEach((pair) => {{
      const cmdText = pair[0];
      const desc = pair[1];
      const row = document.createElement('div');
      row.className = 'ex';
      row.innerHTML = '<code></code><div class="desc"></div>';
      row.querySelector('code').textContent = cmdText;
      row.querySelector('.desc').textContent = desc;
      row.title = t().copied;
      row.addEventListener('click', () => {{
        copyText(cmdText).then(() => showToast(t().copied));
      }});
      box.appendChild(row);
    }});
    if (scroll) detail.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
  }}

  document.getElementById('btn-cn').addEventListener('click', () => setLang('cn'));
  document.getElementById('btn-en').addEventListener('click', () => setLang('en'));
  setLang(lang);
}})();
  </script>
</body>
</html>
"""
