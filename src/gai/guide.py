"""Generate a local HTML usage guide under ``.gai/guide.html`` (bilingual)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gai.cli_usage import command_examples
from gai.llm.history import project_root
from gai.llm.usage_report import path_to_file_url
from gai.web_prefs import PREF_LANG, PREF_THEME, early_prefs_script

_GUIDE_RELATIVE = Path(".gai") / "guide.html"

# Re-export for callers that only need the URL helper via guide.
__all__ = [
    "guide_path",
    "path_to_file_url",
    "write_guide_html",
]

# Titles/blurbs stay here; example lines are shared with cli_usage.command_examples().
_COMMAND_META: list[dict[str, Any]] = [
    {
        "id": "add",
        "en": {
            "title": "Stage files",
            "blurb": "Wrapper around git add. Defaults to '.' when no path is given.",
        },
        "cn": {
            "title": "暂存文件",
            "blurb": "包装 git add。未指定路径时默认暂存当前目录。",
        },
    },
    {
        "id": "unadd",
        "en": {"title": "Unstage files", "blurb": "Undo staging. Asks for confirmation."},
        "cn": {"title": "撤销暂存", "blurb": "撤销暂存区文件，需确认。"},
    },
    {
        "id": "uncommit",
        "en": {
            "title": "Undo latest commit",
            "blurb": "Soft reset (git reset --soft HEAD~1); changes stay staged.",
        },
        "cn": {
            "title": "撤销最近提交",
            "blurb": "软撤销（git reset --soft HEAD~1）；改动仍保留在暂存区。",
        },
    },
    {
        "id": "review",
        "en": {
            "title": "AI code review",
            "blurb": "Review staged changes only — no commit.",
        },
        "cn": {"title": "AI 代码审查", "blurb": "只审查已暂存变更，不提交。"},
    },
    {
        "id": "commit",
        "en": {
            "title": "Review & commit",
            "blurb": "Review → suggest Conventional Commit message → confirm → commit.",
        },
        "cn": {
            "title": "审查并提交",
            "blurb": "审查 → 建议 Conventional Commits 信息 → 确认 → 提交。",
        },
    },
    {
        "id": "push",
        "en": {
            "title": "Push branch",
            "blurb": "Push current branch; warns when there is nothing to push.",
        },
        "cn": {
            "title": "推送分支",
            "blurb": "推送当前分支；无可推送内容时会提示，不当成成功。",
        },
    },
    {
        "id": "pull",
        "en": {
            "title": "Pull updates",
            "blurb": "Check remote updates, then pull (merge or rebase).",
        },
        "cn": {
            "title": "拉取更新",
            "blurb": "检查远程有更新后确认再拉取（merge 或 rebase）。",
        },
    },
    {
        "id": "report",
        "en": {
            "title": "Work summary",
            "blurb": "Turn recent commits into a paste-ready work report.",
        },
        "cn": {
            "title": "工作总结",
            "blurb": "根据近期提交生成可粘贴的工作总结（周报 / 日报）。",
        },
    },
    {
        "id": "usage",
        "en": {
            "title": "Token usage",
            "blurb": "Local LLM token history (JSONL) and optional ECharts dashboard.",
        },
        "cn": {
            "title": "Token 用量",
            "blurb": "本地大模型 token 用量（JSONL），可生成 ECharts 可视化报告。",
        },
    },
    {
        "id": "balance",
        "en": {
            "title": "API balance",
            "blurb": "Query remaining credit when the provider supports it.",
        },
        "cn": {
            "title": "余额查询",
            "blurb": "查询 API Key 剩余额度（若厂商提供接口）。",
        },
    },
    {
        "id": "config",
        "en": {
            "title": "Configuration",
            "blurb": "View or update ~/.gai/config.toml (env vars still win).",
        },
        "cn": {
            "title": "配置",
            "blurb": "查看或更新 ~/.gai/config.toml（环境变量优先级更高）。",
        },
    },
    {
        "id": "completion",
        "en": {
            "title": "Tab completion",
            "blurb": "Install shell Tab-completion for gai subcommands and options.",
        },
        "cn": {
            "title": "Tab 自动补全",
            "blurb": "为 gai 子命令与选项安装 shell Tab 补全。",
        },
    },
    {
        "id": "guide",
        "en": {
            "title": "This guide",
            "blurb": "Regenerate this HTML page under .gai/guide.html.",
        },
        "cn": {
            "title": "本教程页",
            "blurb": "重新生成 .gai/guide.html 可视化教程。",
        },
    },
]


def guide_path(cwd: Path | None = None) -> Path:
    return project_root(cwd) / _GUIDE_RELATIVE


def _commands() -> list[dict[str, Any]]:
    """Structured command cards; examples come from cli_usage (single source)."""
    out: list[dict[str, Any]] = []
    for meta in _COMMAND_META:
        cmd_id = meta["id"]
        examples = command_examples(cmd_id)
        en_ex = [(line, en) for line, en, _cn in examples]
        cn_ex = [(line, cn) for line, _en, cn in examples]
        out.append(
            {
                "id": cmd_id,
                "name": cmd_id,
                "en": {**meta["en"], "examples": en_ex},
                "cn": {**meta["cn"], "examples": cn_ex},
            }
        )
    return out


def _i18n() -> dict[str, dict[str, str]]:
    return {
        "cn": {
            "doc_title": "gai 使用指南",
            "brand": "gai",
            "tagline": "本地 Git 提交与代码审查 Agent",
            "lang_cn": "中文",
            "lang_en": "EN",
            "nav_menu": "目录",
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
            "commands_hint": "点击卡片在右侧抽屉查看详情；抽屉内可直接切换其他命令。支持搜索与深链 #commit。",
            "search_ph": "搜索命令…",
            "search_empty": "没有匹配的命令",
            "examples_h": "示例",
            "drawer_switch": "切换命令",
            "drawer_close": "关闭",
            "theme_light": "日间",
            "theme_dark": "夜间",
            "copied": "已复制",
            "tips_h": "提示与约定",
            "tips": [
                "审查 / 提交只看 staged diff（git diff --cached），不会偷偷提交未暂存文件。",
                "不拦截原生 git：也可用 --no-ai -m 或直接 git commit / git push。",
                "用量报告：gai usage --report / --serve → .gai/usage-report.html",
                "本教程：gai guide [--cn] [--open|--serve] → .gai/guide.html；深链如 guide.html#commit",
                "主题与语言偏好与用量报告共用（gai-ui-theme / gai-ui-lang）",
                "PowerShell Tab 补全：gai completion install --shell powershell --cn，然后重开终端",
            ],
            "footer": "由 gai guide 生成 · 存放于仓库 .gai/guide.html · 页面内可切换中/英与日间/夜间主题",
            "generated": "生成时间",
        },
        "en": {
            "doc_title": "gai User Guide",
            "brand": "gai",
            "tagline": "Local Git commit & code review agent",
            "lang_cn": "中文",
            "lang_en": "EN",
            "nav_menu": "Contents",
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
            "commands_hint": "Click a card for the side drawer. Search commands or deep-link with #commit.",
            "search_ph": "Search commands…",
            "search_empty": "No matching commands",
            "examples_h": "Examples",
            "drawer_switch": "Switch command",
            "drawer_close": "Close",
            "theme_light": "Light",
            "theme_dark": "Dark",
            "copied": "Copied",
            "tips_h": "Tips & conventions",
            "tips": [
                "Review/commit only look at staged diffs (git diff --cached).",
                "Native git stays available: use --no-ai -m or plain git commit / git push.",
                "Usage dashboard: gai usage --report / --serve → .gai/usage-report.html",
                "This guide: gai guide [--cn] [--open|--serve] → .gai/guide.html; deep links like guide.html#commit",
                "Theme/language prefs are shared with the usage report (gai-ui-theme / gai-ui-lang)",
                "PowerShell Tab completion: gai completion install --shell powershell --cn, then restart the terminal",
            ],
            "footer": "Generated by gai guide · stored at .gai/guide.html · switch language and light/dark theme anytime",
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
<html lang="en" data-lang="{payload["initialLang"]}" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gai guide</title>
  <script>
  {early_prefs_script(default_lang=payload["initialLang"], default_theme="light")}
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Sora:wght@500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --ink: #10233f;
      --ink-soft: #3d516c;
      --muted: #6b7c93;
      --line: #d7e0ec;
      --paper: #f3f6fa;
      --paper-2: #eaf0f7;
      --bg0: #f7fafc;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --surface-hover: #f0fdfa;
      --teal: #0f766e;
      --teal-soft: #ccfbf1;
      --on-ink: #ffffff;
      --top-bg: rgba(247, 250, 252, .82);
      --glow-a: rgba(15,118,110,.10);
      --glow-b: rgba(180,83,9,.07);
      --mask: rgba(16, 35, 63, .42);
      --drawer-shadow: -18px 0 50px rgba(16,35,63,.16);
      --card-active: linear-gradient(180deg, #f0fdfa, #fff 48%);
      --radius: 14px;
      --font: "Sora", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: "IBM Plex Mono", "Cascadia Code", Consolas, monospace;
      --shadow: 0 1px 0 rgba(16,35,63,.04), 0 18px 40px rgba(16,35,63,.07);
      --terminal-bg: #142033;
      --terminal-fg: #dbeafe;
    }}
    html[data-theme="dark"] {{
      --ink: #e8eef9;
      --ink-soft: #c2cede;
      --muted: #94a3b8;
      --line: rgba(148, 163, 184, 0.22);
      --paper: #121a2b;
      --paper-2: #0b1220;
      --bg0: #0b1220;
      --surface: #182338;
      --surface-2: #142033;
      --surface-hover: #1c3348;
      --teal: #2dd4bf;
      --teal-soft: rgba(45, 212, 191, .16);
      --on-ink: #0b1220;
      --top-bg: rgba(11, 18, 32, .86);
      --glow-a: rgba(45, 212, 191, .12);
      --glow-b: rgba(56, 189, 248, .08);
      --mask: rgba(2, 8, 20, .62);
      --drawer-shadow: -18px 0 50px rgba(0,0,0,.45);
      --card-active: linear-gradient(180deg, rgba(45,212,191,.14), #182338 48%);
      --shadow: 0 1px 0 rgba(255,255,255,.04) inset, 0 18px 40px rgba(0,0,0,.35);
      --terminal-bg: #0a1220;
      --terminal-fg: #dbeafe;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      min-height: 100%;
      color: var(--ink);
      font-family: var(--font);
      background:
        radial-gradient(900px 420px at 8% -8%, var(--glow-a), transparent 55%),
        radial-gradient(700px 380px at 92% 0%, var(--glow-b), transparent 50%),
        linear-gradient(180deg, var(--bg0) 0%, var(--paper) 40%, var(--paper-2) 100%);
    }}
    a {{ color: var(--teal); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    @media (prefers-reduced-motion: no-preference) {{
      html.theme-ready body,
      html.theme-ready .top,
      html.theme-ready .seg,
      html.theme-ready .seg button,
      html.theme-ready .nav a,
      html.theme-ready .step,
      html.theme-ready .note,
      html.theme-ready .cmd-card,
      html.theme-ready .tips li,
      html.theme-ready .drawer,
      html.theme-ready .drawer-close,
      html.theme-ready .drawer-switch button,
      html.theme-ready .ex,
      html.theme-ready .terminal,
      html.theme-ready footer,
      html.theme-ready .toast {{
        transition:
          background .42s cubic-bezier(.22, 1, .36, 1),
          background-color .42s cubic-bezier(.22, 1, .36, 1),
          color .42s cubic-bezier(.22, 1, .36, 1),
          border-color .42s cubic-bezier(.22, 1, .36, 1),
          box-shadow .42s cubic-bezier(.22, 1, .36, 1),
          opacity .42s cubic-bezier(.22, 1, .36, 1);
      }}
      html.theme-ready .brand,
      html.theme-ready .brand span,
      html.theme-ready .tagline,
      html.theme-ready .hero h1,
      html.theme-ready .hero p,
      html.theme-ready .sec-head,
      html.theme-ready .hint,
      html.theme-ready .blurb,
      html.theme-ready .meta,
      html.theme-ready .cmd-card .name,
      html.theme-ready .cmd-card .title,
      html.theme-ready .step .cmd,
      html.theme-ready .step .desc,
      html.theme-ready .step .n {{
        transition: color .42s cubic-bezier(.22, 1, .36, 1), background .42s cubic-bezier(.22, 1, .36, 1);
      }}
      ::view-transition-old(root),
      ::view-transition-new(root) {{
        animation-duration: .45s;
        animation-timing-function: cubic-bezier(.22, 1, .36, 1);
      }}
    }}

    .top {{
      position: sticky;
      top: 0;
      z-index: 20;
      backdrop-filter: blur(14px);
      background: var(--top-bg);
      border-bottom: 1px solid var(--line);
    }}
    .top-inner {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 14px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand-wrap {{
      display: flex;
      align-items: baseline;
      gap: 12px;
      min-width: 0;
    }}
    .brand {{
      font-size: 1.55rem;
      font-weight: 700;
      letter-spacing: -.04em;
      color: var(--ink);
      line-height: 1;
    }}
    .brand span {{
      color: var(--teal);
    }}
    .tagline {{
      color: var(--muted);
      font-size: .84rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .top-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }}
    .seg {{
      display: inline-flex;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 10px;
      overflow: hidden;
      flex: 0 0 auto;
    }}
    .seg button {{
      border: 0;
      background: transparent;
      color: var(--muted);
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
      font-size: .8rem;
      font-weight: 600;
    }}
    .seg button.active {{
      background: var(--ink);
      color: var(--on-ink);
    }}

    .shell {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 28px 64px;
      display: grid;
      grid-template-columns: 188px minmax(0, 1fr);
      gap: 36px;
      align-items: start;
    }}
    .side {{
      position: sticky;
      top: 72px;
      max-height: calc(100vh - 88px);
      overflow: auto;
      padding-right: 4px;
    }}
    .nav-label {{
      font-size: .72rem;
      font-weight: 600;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--muted);
      margin: 0 0 10px 8px;
    }}
    .nav {{
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .nav a {{
      color: var(--ink-soft);
      padding: 8px 10px;
      border-radius: 10px;
      font-size: .9rem;
      font-weight: 500;
      text-decoration: none;
      border-left: 2px solid transparent;
    }}
    .nav a:hover {{
      background: rgba(15,118,110,.08);
      color: var(--teal);
      text-decoration: none;
    }}
    .nav .cmd {{
      font-family: var(--mono);
      font-size: .76rem;
      color: var(--muted);
      padding: 5px 10px 5px 18px;
      font-weight: 500;
    }}
    .nav .cmd:hover {{ color: var(--teal); }}

    .main {{ min-width: 0; }}
    section {{
      margin-bottom: 40px;
      scroll-margin-top: 84px;
      animation: rise .45s ease both;
    }}
    section:nth-of-type(2) {{ animation-delay: .04s; }}
    section:nth-of-type(3) {{ animation-delay: .08s; }}
    section:nth-of-type(4) {{ animation-delay: .12s; }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: none; }}
    }}

    .hero {{
      padding: 8px 0 8px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 36px;
    }}
    .hero-kicker {{
      display: inline-block;
      font-size: .75rem;
      font-weight: 600;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: var(--teal);
      margin-bottom: 10px;
    }}
    .hero h1 {{
      margin: 0 0 12px;
      font-size: clamp(1.8rem, 3.2vw, 2.4rem);
      font-weight: 700;
      letter-spacing: -.035em;
      line-height: 1.15;
      color: var(--ink);
    }}
    .hero p {{
      margin: 0;
      max-width: 46rem;
      color: var(--ink-soft);
      font-size: 1.02rem;
      line-height: 1.65;
    }}
    .meta {{
      margin-top: 18px;
      color: var(--muted);
      font-size: .78rem;
    }}

    .sec-head {{
      margin: 0 0 14px;
      font-size: 1.2rem;
      font-weight: 700;
      letter-spacing: -.02em;
    }}
    .hint {{
      margin: -6px 0 16px;
      color: var(--muted);
      font-size: .88rem;
    }}
    .blurb {{
      margin: 0;
      color: var(--ink-soft);
      font-size: .92rem;
      line-height: 1.6;
    }}

    .steps {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      counter-reset: step;
    }}
    .step {{
      position: relative;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px 12px 14px;
      box-shadow: var(--shadow);
      min-height: 118px;
    }}
    .step .n {{
      display: inline-flex;
      width: 26px;
      height: 26px;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      background: var(--teal-soft);
      color: var(--teal);
      font-family: var(--mono);
      font-size: .78rem;
      font-weight: 600;
      margin-bottom: 10px;
    }}
    .step .cmd {{
      font-family: var(--mono);
      font-size: .78rem;
      font-weight: 600;
      color: var(--ink);
      margin-bottom: 6px;
      word-break: break-word;
    }}
    .step .desc {{
      color: var(--muted);
      font-size: .78rem;
      line-height: 1.45;
    }}

    .setup-grid {{
      display: grid;
      grid-template-columns: 1.15fr .85fr;
      gap: 16px;
      align-items: stretch;
    }}
    .terminal {{
      background: var(--terminal-bg);
      color: var(--terminal-fg);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }}
    .terminal-bar {{
      display: flex;
      gap: 6px;
      padding: 12px 14px;
      background: rgba(255,255,255,.04);
      border-bottom: 1px solid rgba(255,255,255,.06);
    }}
    .terminal-bar i {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #475569;
      display: block;
    }}
    .terminal-bar i:nth-child(1) {{ background: #f87171; }}
    .terminal-bar i:nth-child(2) {{ background: #fbbf24; }}
    .terminal-bar i:nth-child(3) {{ background: #34d399; }}
    pre.install {{
      margin: 0;
      padding: 16px 18px 18px;
      overflow: auto;
      font-family: var(--mono);
      font-size: .82rem;
      line-height: 1.65;
      white-space: pre-wrap;
    }}
    .setup-notes {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .note {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow);
    }}
    .note strong {{
      display: block;
      font-size: .82rem;
      margin-bottom: 4px;
      color: var(--ink);
    }}

    .cmd-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .cmd-card {{
      display: block;
      width: 100%;
      text-align: left;
      font: inherit;
      color: inherit;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px 16px 14px;
      cursor: pointer;
      box-shadow: var(--shadow);
      border-top: 3px solid transparent;
    }}
    html.theme-ready .cmd-card {{
      transition:
        transform .18s ease,
        border-color .42s cubic-bezier(.22, 1, .36, 1),
        box-shadow .42s cubic-bezier(.22, 1, .36, 1),
        background .42s cubic-bezier(.22, 1, .36, 1),
        color .42s cubic-bezier(.22, 1, .36, 1);
    }}
    .cmd-card:hover {{
      transform: translateY(-3px);
      border-color: rgba(15,118,110,.35);
      border-top-color: var(--teal);
      box-shadow: 0 16px 36px rgba(16,35,63,.1);
    }}
    .cmd-card.active {{
      border-color: rgba(15,118,110,.45);
      border-top-color: var(--teal);
      background: var(--card-active);
    }}
    .cmd-card .name {{
      font-family: var(--mono);
      font-size: .84rem;
      font-weight: 600;
      color: var(--teal);
    }}
    .cmd-card .title {{
      margin-top: 8px;
      font-size: .98rem;
      font-weight: 650;
      color: var(--ink);
    }}
    .cmd-card .blurb {{
      margin-top: 6px;
      font-size: .82rem;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .drawer-root {{
      position: fixed;
      inset: 0;
      z-index: 40;
      pointer-events: none;
    }}
    .drawer-root.open {{ pointer-events: auto; }}
    .drawer-mask {{
      position: absolute;
      inset: 0;
      background: var(--mask);
      opacity: 0;
      transition: opacity .22s ease;
    }}
    .drawer-root.open .drawer-mask {{ opacity: 1; }}
    .drawer {{
      position: absolute;
      top: 0;
      right: 0;
      width: min(440px, 100%);
      height: 100%;
      background: var(--surface);
      border-left: 1px solid var(--line);
      box-shadow: var(--drawer-shadow);
      transform: translateX(104%);
      transition: transform .24s ease;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .drawer-root.open .drawer {{ transform: none; }}
    .drawer-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 18px 18px 12px;
      border-bottom: 1px solid var(--line);
      flex: 0 0 auto;
    }}
    .drawer-head h2 {{
      margin: 0;
      font-size: 1.15rem;
      letter-spacing: -.02em;
      line-height: 1.25;
    }}
    .drawer-close {{
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink-soft);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
      font-size: .8rem;
      font-weight: 600;
      flex: 0 0 auto;
    }}
    .drawer-close:hover {{ border-color: rgba(15,118,110,.4); color: var(--teal); }}
    .drawer-switch-label {{
      margin: 0;
      padding: 12px 18px 8px;
      font-size: .72rem;
      font-weight: 600;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: var(--muted);
      flex: 0 0 auto;
    }}
    .drawer-switch {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 0 18px 12px;
      border-bottom: 1px solid var(--line);
      flex: 0 0 auto;
      max-height: 140px;
      overflow: auto;
    }}
    .drawer-switch button {{
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink-soft);
      border-radius: 8px;
      padding: 6px 10px;
      cursor: pointer;
      font-family: var(--mono);
      font-size: .74rem;
      font-weight: 500;
    }}
    .drawer-switch button:hover {{
      border-color: rgba(15,118,110,.35);
      color: var(--teal);
    }}
    .drawer-switch button.active {{
      background: var(--ink);
      border-color: var(--ink);
      color: var(--on-ink);
    }}
    .drawer-body {{
      padding: 16px 18px 28px;
      overflow: auto;
      flex: 1 1 auto;
      min-height: 0;
    }}
    .drawer-body .blurb {{
      margin: 0 0 4px;
    }}
    .drawer-body h3 {{
      margin: 16px 0 8px;
      font-size: .86rem;
      color: var(--muted);
      font-weight: 600;
      letter-spacing: .04em;
      text-transform: uppercase;
    }}
    .examples {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .ex {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px 12px;
      align-items: start;
      padding: 12px 14px;
      border-radius: 12px;
      background: var(--surface-2);
      border: 1px solid var(--line);
      cursor: pointer;
      transition: border-color .15s ease, background .15s ease;
    }}
    .ex:hover {{
      border-color: rgba(15,118,110,.4);
      background: var(--surface-hover);
    }}
    .ex code {{
      font-family: var(--mono);
      font-size: .82rem;
      color: var(--ink);
      word-break: break-all;
      grid-column: 1 / 2;
    }}
    .ex .desc {{
      color: var(--muted);
      font-size: .82rem;
      line-height: 1.4;
      grid-column: 1 / 2;
    }}
    .ex .copy {{
      grid-column: 2 / 3;
      grid-row: 1 / 3;
      align-self: center;
      font-size: .72rem;
      font-weight: 600;
      color: var(--teal);
      letter-spacing: .04em;
      text-transform: uppercase;
    }}
    body.drawer-open {{ overflow: hidden; }}

    .tips {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .tips li {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px 12px 16px;
      color: var(--ink-soft);
      font-size: .9rem;
      line-height: 1.55;
      box-shadow: var(--shadow);
      border-left: 3px solid var(--teal);
    }}

    footer {{
      margin-top: 8px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: .78rem;
    }}
    .toast {{
      position: fixed;
      bottom: 22px;
      right: 22px;
      padding: 10px 16px;
      border-radius: 10px;
      background: var(--ink);
      color: var(--on-ink);
      font-weight: 600;
      font-size: .85rem;
      opacity: 0;
      pointer-events: none;
      transition: opacity .2s ease, transform .2s ease;
      transform: translateY(6px);
      z-index: 50;
    }}
    .toast.show {{ opacity: 1; transform: none; }}
    .cmd-search {{
      width: min(100%, 420px);
      margin: 0 0 14px;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      font: inherit;
      font-size: .92rem;
      box-shadow: var(--shadow);
    }}
    .cmd-search:focus-visible {{
      outline: 2px solid var(--teal);
      outline-offset: 2px;
    }}
    .cmd-empty {{
      color: var(--muted);
      font-size: .9rem;
      padding: 8px 2px 4px;
    }}
    button:focus-visible, .seg button:focus-visible, .cmd-card:focus-visible, .ex:focus-visible {{
      outline: 2px solid var(--teal);
      outline-offset: 2px;
    }}

    @media (max-width: 960px) {{
      .steps {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .cmd-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .setup-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 780px) {{
      .shell {{ grid-template-columns: 1fr; gap: 18px; padding: 18px 16px 48px; }}
      .side {{
        position: relative;
        top: 0;
        max-height: none;
        overflow: visible;
      }}
      .nav {{
        flex-direction: row;
        flex-wrap: wrap;
        gap: 6px;
      }}
      .nav a {{
        border: 1px solid var(--line);
        background: var(--surface);
        border-left: 0;
        padding: 7px 10px;
        font-size: .8rem;
      }}
      .nav-label {{ display: none; }}
      .top-inner {{ padding: 12px 16px; }}
      .tagline {{ display: none; }}
      .steps {{ grid-template-columns: 1fr; }}
      .cmd-grid {{ grid-template-columns: 1fr; }}
      .drawer {{ width: 100%; }}
      .ex .copy {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header class="top">
    <div class="top-inner">
      <div class="brand-wrap">
        <div class="brand"><span data-i="brand">gai</span></div>
        <div class="tagline" data-i="tagline"></div>
      </div>
      <div class="top-actions">
        <div class="seg" role="group" aria-label="Theme">
          <button type="button" id="btn-theme-light" data-i="theme_light">日间</button>
          <button type="button" id="btn-theme-dark" data-i="theme_dark">夜间</button>
        </div>
        <div class="seg" role="group" aria-label="Language">
          <button type="button" id="btn-cn" data-lang="cn">中文</button>
          <button type="button" id="btn-en" data-lang="en">EN</button>
        </div>
      </div>
    </div>
  </header>

  <div class="shell">
    <aside class="side">
      <div class="nav-label" data-i="nav_menu"></div>
      <nav class="nav" id="side-nav">
        <a href="#overview" data-i="nav_overview"></a>
        <a href="#flow" data-i="nav_flow"></a>
        <a href="#setup" data-i="nav_setup"></a>
        <a href="#commands" data-i="nav_commands"></a>
        <a href="#tips" data-i="nav_tips"></a>
      </nav>
    </aside>

    <main class="main">
      <section class="hero" id="overview">
        <div class="hero-kicker" data-i="overview_h"></div>
        <h1 data-i="doc_title"></h1>
        <p data-i="overview_p"></p>
        <div class="meta"><span data-i="generated"></span>: <span id="gen-time"></span></div>
      </section>

      <section id="flow">
        <h2 class="sec-head" data-i="flow_h"></h2>
        <div class="steps" id="flow-list"></div>
      </section>

      <section id="setup">
        <h2 class="sec-head" data-i="setup_h"></h2>
        <div class="setup-grid">
          <div class="terminal">
            <div class="terminal-bar"><i></i><i></i><i></i></div>
            <pre class="install">python -m pip install -e ".[dev]"
gai --version
gai config --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat</pre>
          </div>
          <div class="setup-notes">
            <div class="note">
              <strong data-i="setup_install"></strong>
              <p class="blurb" data-i="setup_config"></p>
            </div>
            <div class="note">
              <strong>API</strong>
              <p class="blurb" data-i="setup_keys"></p>
            </div>
            <div class="note">
              <strong>--cn</strong>
              <p class="blurb" data-i="setup_cn"></p>
            </div>
          </div>
        </div>
      </section>

      <section id="commands">
        <h2 class="sec-head" data-i="commands_h"></h2>
        <p class="hint" data-i="commands_hint"></p>
        <input type="search" class="cmd-search" id="cmd-search"
               data-i-placeholder="search_ph" placeholder="Search commands…"
               autocomplete="off" aria-label="Search commands" />
        <div class="cmd-empty" id="cmd-empty" hidden data-i="search_empty"></div>
        <div class="cmd-grid" id="cmd-grid"></div>
      </section>

      <section id="tips">
        <h2 class="sec-head" data-i="tips_h"></h2>
        <ul class="tips" id="tips-list"></ul>
      </section>

      <footer data-i="footer"></footer>
    </main>
  </div>

  <div class="drawer-root" id="drawer-root" aria-hidden="true">
    <div class="drawer-mask" id="drawer-mask"></div>
    <aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div class="drawer-head">
        <h2 id="detail-title"></h2>
        <button type="button" class="drawer-close" id="drawer-close" data-i="drawer_close">关闭</button>
      </div>
      <p class="drawer-switch-label" data-i="drawer_switch"></p>
      <div class="drawer-switch" id="drawer-switch"></div>
      <div class="drawer-body">
        <p class="blurb" id="detail-blurb"></p>
        <h3 data-i="examples_h"></h3>
        <div class="examples" id="detail-examples"></div>
      </div>
    </aside>
  </div>

  <div class="toast" id="toast"></div>
  <script id="guide-data" type="application/json">{data_json}</script>
  <script>
(function () {{
  const DATA = JSON.parse(document.getElementById('guide-data').textContent);
  let lang = document.documentElement.getAttribute('data-lang') === 'cn'
    ? 'cn'
    : (DATA.initialLang === 'cn' ? 'cn' : 'en');
  let openId = '';
  let searchQ = '';
  const toast = document.getElementById('toast');
  const drawerRoot = document.getElementById('drawer-root');
  const searchInput = document.getElementById('cmd-search');
  let toastTimer = null;
  let lastFocus = null;
  const copyLabel = {{ cn: '复制', en: 'Copy' }};

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

  function splitFlow(step) {{
    const parts = step.split(/\\s*[—–-]\\s*/);
    if (parts.length >= 2) {{
      return {{ cmd: parts[0].trim(), desc: parts.slice(1).join(' — ').trim() }};
    }}
    return {{ cmd: step, desc: '' }};
  }}

  function closeDrawer({{ clearHash = true }} = {{}}) {{
    drawerRoot.classList.remove('open');
    drawerRoot.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('drawer-open');
    openId = '';
    document.querySelectorAll('.cmd-card').forEach((el) => el.classList.remove('active'));
    if (clearHash && location.hash && DATA.commands.some((c) => '#' + c.id === location.hash)) {{
      history.replaceState(null, '', location.pathname + location.search);
    }}
    if (lastFocus && typeof lastFocus.focus === 'function') {{
      try {{ lastFocus.focus(); }} catch (e) {{}}
    }}
    lastFocus = null;
  }}

  function currentTheme() {{
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }}

  function applyTheme(theme) {{
    document.documentElement.setAttribute('data-theme', theme);
    try {{ localStorage.setItem('{PREF_THEME}', theme); }} catch (e) {{}}
    document.getElementById('btn-theme-light').classList.toggle('active', theme === 'light');
    document.getElementById('btn-theme-dark').classList.toggle('active', theme === 'dark');
  }}

  function setTheme(next, {{ animate = true }} = {{}}) {{
    const theme = next === 'dark' ? 'dark' : 'light';
    if (theme === currentTheme()) {{
      applyTheme(theme);
      return;
    }}
    const run = () => applyTheme(theme);
    if (
      animate &&
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
    document.documentElement.setAttribute('data-lang', lang);
    document.documentElement.lang = lang === 'cn' ? 'zh-CN' : 'en';
    try {{ localStorage.setItem('{PREF_LANG}', lang); }} catch (e) {{}}
    document.getElementById('btn-cn').classList.toggle('active', lang === 'cn');
    document.getElementById('btn-en').classList.toggle('active', lang === 'en');
    document.title = t().doc_title;
    document.querySelectorAll('[data-i]').forEach((el) => {{
      const key = el.getAttribute('data-i');
      const val = t()[key];
      if (typeof val === 'string') el.textContent = val;
    }});
    document.querySelectorAll('[data-i-placeholder]').forEach((el) => {{
      const key = el.getAttribute('data-i-placeholder');
      const val = t()[key];
      if (typeof val === 'string') el.setAttribute('placeholder', val);
    }});
    if (searchInput) searchInput.setAttribute('aria-label', t().search_ph || 'Search');
    document.getElementById('gen-time').textContent = DATA.generated;

    const flow = document.getElementById('flow-list');
    flow.innerHTML = '';
    (t().flow_steps || []).forEach((step, idx) => {{
      const parts = splitFlow(step);
      const el = document.createElement('div');
      el.className = 'step';
      el.innerHTML =
        '<div class="n"></div><div class="cmd"></div><div class="desc"></div>';
      el.querySelector('.n').textContent = String(idx + 1);
      el.querySelector('.cmd').textContent = parts.cmd;
      el.querySelector('.desc').textContent = parts.desc;
      flow.appendChild(el);
    }});

    const tips = document.getElementById('tips-list');
    tips.innerHTML = '';
    (t().tips || []).forEach((tip) => {{
      const li = document.createElement('li');
      li.textContent = tip;
      tips.appendChild(li);
    }});

    renderCommands();
    renderDrawerSwitch();
    if (openId) openCommand(openId, {{ updateHash: false }});
  }}

  function cmdLocale(cmd) {{
    return lang === 'cn' ? cmd.cn : cmd.en;
  }}

  function matchesSearch(cmd) {{
    const q = searchQ.trim().toLowerCase();
    if (!q) return true;
    const loc = cmdLocale(cmd);
    const hay = [
      cmd.name,
      loc.title,
      loc.blurb,
      ...(loc.examples || []).flatMap((p) => [p[0], p[1]]),
    ].join(' ').toLowerCase();
    return hay.includes(q);
  }}

  function renderDrawerSwitch() {{
    const box = document.getElementById('drawer-switch');
    box.innerHTML = '';
    DATA.commands.forEach((cmd) => {{
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = cmd.name;
      btn.className = openId === cmd.id ? 'active' : '';
      btn.addEventListener('click', () => openCommand(cmd.id));
      box.appendChild(btn);
    }});
  }}

  function renderCommands() {{
    const grid = document.getElementById('cmd-grid');
    const empty = document.getElementById('cmd-empty');
    grid.innerHTML = '';
    let shown = 0;
    DATA.commands.forEach((cmd) => {{
      if (!matchesSearch(cmd)) return;
      shown += 1;
      const loc = cmdLocale(cmd);
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'cmd-card' + (openId === cmd.id ? ' active' : '');
      card.id = 'cmd-' + cmd.id;
      card.setAttribute('data-cmd', cmd.id);
      card.innerHTML =
        '<div class="name">gai ' + cmd.name + '</div>' +
        '<div class="title"></div>' +
        '<p class="blurb"></p>';
      card.querySelector('.title').textContent = loc.title;
      card.querySelector('.blurb').textContent = loc.blurb;
      card.addEventListener('click', () => openCommand(cmd.id));
      grid.appendChild(card);
    }});
    if (empty) {{
      empty.hidden = shown > 0;
      empty.textContent = t().search_empty || '';
    }}
  }}

  function openCommand(id, {{ updateHash = true }} = {{}}) {{
    const cmd = DATA.commands.find((c) => c.id === id);
    if (!cmd) return;
    const loc = cmdLocale(cmd);
    if (!drawerRoot.classList.contains('open')) {{
      lastFocus = document.activeElement;
    }}
    openId = id;
    drawerRoot.classList.add('open');
    drawerRoot.setAttribute('aria-hidden', 'false');
    document.body.classList.add('drawer-open');
    document.querySelectorAll('.cmd-card').forEach((el) => {{
      el.classList.toggle('active', el.getAttribute('data-cmd') === id);
    }});
    document.querySelectorAll('#drawer-switch button').forEach((btn) => {{
      btn.classList.toggle('active', btn.textContent === cmd.name);
    }});
    document.getElementById('detail-title').textContent = 'gai ' + cmd.name + ' — ' + loc.title;
    document.getElementById('detail-blurb').textContent = loc.blurb;
    const box = document.getElementById('detail-examples');
    box.innerHTML = '';
    (loc.examples || []).forEach((pair) => {{
      const cmdText = pair[0];
      const desc = pair[1];
      const row = document.createElement('div');
      row.className = 'ex';
      row.setAttribute('role', 'button');
      row.tabIndex = 0;
      row.innerHTML = '<code></code><div class="desc"></div><div class="copy"></div>';
      row.querySelector('code').textContent = cmdText;
      row.querySelector('.desc').textContent = desc;
      row.querySelector('.copy').textContent = copyLabel[lang];
      const copy = () => copyText(cmdText).then(() => showToast(t().copied));
      row.addEventListener('click', copy);
      row.addEventListener('keydown', (e) => {{
        if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); copy(); }}
      }});
      box.appendChild(row);
    }});
    if (updateHash) {{
      const next = '#' + id;
      if (location.hash !== next) history.replaceState(null, '', next);
    }}
    const closeBtn = document.getElementById('drawer-close');
    if (closeBtn) closeBtn.focus();
  }}

  function applyHash() {{
    const raw = (location.hash || '').replace(/^#/, '').trim().toLowerCase();
    if (!raw) return;
    if (DATA.commands.some((c) => c.id === raw)) {{
      openCommand(raw, {{ updateHash: false }});
      const card = document.getElementById('cmd-' + raw);
      if (card) card.scrollIntoView({{ block: 'nearest' }});
    }}
  }}

  document.getElementById('btn-cn').addEventListener('click', () => setLang('cn'));
  document.getElementById('btn-en').addEventListener('click', () => setLang('en'));
  document.getElementById('btn-theme-light').addEventListener('click', () => setTheme('light'));
  document.getElementById('btn-theme-dark').addEventListener('click', () => setTheme('dark'));
  document.getElementById('drawer-close').addEventListener('click', () => closeDrawer());
  document.getElementById('drawer-mask').addEventListener('click', () => closeDrawer());
  if (searchInput) {{
    searchInput.addEventListener('input', () => {{
      searchQ = searchInput.value || '';
      renderCommands();
    }});
  }}
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape' && drawerRoot.classList.contains('open')) {{
      closeDrawer();
      return;
    }}
    if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) &&
        document.activeElement !== searchInput) {{
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag !== 'INPUT' && tag !== 'TEXTAREA') {{
        e.preventDefault();
        if (searchInput) searchInput.focus();
      }}
    }}
  }});
  window.addEventListener('hashchange', applyHash);
  setTheme(currentTheme(), {{ animate: false }});
  setLang(lang);
  applyHash();
  requestAnimationFrame(() => {{
    document.documentElement.classList.add('theme-ready');
  }});
}})();
  </script>
</body>
</html>
"""
