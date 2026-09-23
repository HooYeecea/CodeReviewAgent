"""Work-report engine: summarize git commit history via LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from gai.config import Settings, load_settings
from gai.git_ops import (
    CommitInfo,
    current_author_filter,
    ensure_repo,
    format_commits_for_prompt,
    get_commits,
    is_alltime_token,
    resolve_since,
)
from gai.llm.client import LLMClient, LLMError
from gai.llm.prompts import REPORT_SYSTEM_PROMPT, build_report_user_prompt

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

DEFAULT_SINCE = "7d"
DEFAULT_MAX_COMMITS = 100
ALLTIME_DEFAULT_MAX_COMMITS = 500


@dataclass
class ReportCategory:
    name: str
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "items": list(self.items)}


@dataclass
class ReportResult:
    period_summary: str = ""
    highlights: list[str] = field(default_factory=list)
    categories: list[ReportCategory] = field(default_factory=list)
    report_markdown: str = ""
    commit_count: int = 0
    commits: list[CommitInfo] = field(default_factory=list)
    since: str | None = None
    until: str | None = None
    author: str | None = None
    raw_text: str = ""
    parsed_ok: bool = True
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_summary": self.period_summary,
            "highlights": list(self.highlights),
            "categories": [c.to_dict() for c in self.categories],
            "report_markdown": self.report_markdown,
            "commit_count": self.commit_count,
            "since": self.since,
            "until": self.until,
            "author": self.author,
            "parsed_ok": self.parsed_ok,
            "truncated": self.truncated,
            "commits": [c.to_dict() for c in self.commits],
        }


def _extract_json_blob(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    fence = _JSON_FENCE.search(text)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return None


def parse_report_response(text: str) -> ReportResult:
    blob = _extract_json_blob(text)
    if not blob:
        return ReportResult(raw_text=text, parsed_ok=False, report_markdown=text.strip()[:4000])

    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return ReportResult(raw_text=text, parsed_ok=False, report_markdown=text.strip()[:4000])

    if not isinstance(data, dict):
        return ReportResult(raw_text=text, parsed_ok=False, report_markdown=str(data)[:4000])

    highlights_raw = data.get("highlights") or []
    highlights = [str(x).strip() for x in highlights_raw if str(x).strip()] if isinstance(highlights_raw, list) else []

    categories: list[ReportCategory] = []
    cats_raw = data.get("categories") or []
    if isinstance(cats_raw, list):
        for entry in cats_raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            items_raw = entry.get("items") or []
            items = (
                [str(x).strip() for x in items_raw if str(x).strip()]
                if isinstance(items_raw, list)
                else []
            )
            if name or items:
                categories.append(ReportCategory(name=name or "Other", items=items))

    commit_count = data.get("commit_count")
    try:
        commit_count_int = int(commit_count) if commit_count is not None else 0
    except (TypeError, ValueError):
        commit_count_int = 0

    return ReportResult(
        period_summary=str(data.get("period_summary") or "").strip(),
        highlights=highlights,
        categories=categories,
        report_markdown=str(data.get("report_markdown") or "").strip(),
        commit_count=commit_count_int,
        raw_text=text,
        parsed_ok=True,
    )


def run_report(
    *,
    settings: Settings | None = None,
    since: str | None = DEFAULT_SINCE,
    until: str | None = None,
    author: str | None = None,
    max_count: int = DEFAULT_MAX_COMMITS,
    include_stat: bool = True,
    chinese: bool = False,
    alltime: bool = False,
) -> ReportResult:
    """Load commit history and ask the LLM for a work-report summary."""
    settings = settings or load_settings()
    ensure_repo()

    alltime_mode = bool(alltime) or is_alltime_token(since)
    if alltime_mode:
        since_resolved = None
        since_label: str | None = "alltime"
        if max_count == DEFAULT_MAX_COMMITS:
            max_count = ALLTIME_DEFAULT_MAX_COMMITS
    else:
        since_resolved = resolve_since(since) if since else None
        since_label = since_resolved

    until_resolved = until.strip() if until and until.strip() else None

    author_filter = author
    if author_filter and author_filter.strip().lower() in {"me", "self"}:
        author_filter = current_author_filter()
    elif author_filter is not None:
        author_filter = author_filter.strip() or None

    commits = get_commits(
        since=since_resolved,
        until=until_resolved,
        author=author_filter,
        max_count=max_count,
        include_stat=include_stat,
    )
    if not commits:
        raise RuntimeError(
            "No commits found in the selected range. "
            "Try a wider --since / --alltime or drop --author."
        )

    commits_text, truncated = format_commits_for_prompt(
        commits,
        max_chars=settings.max_diff_chars,
    )

    client = LLMClient(settings)
    user_prompt = build_report_user_prompt(
        commits_text=commits_text,
        since=since_label,
        until=until_resolved,
        author=author_filter,
        commit_count=len(commits),
        truncated=truncated,
        chinese=chinese,
    )

    try:
        raw = client.chat(system=REPORT_SYSTEM_PROMPT, user=user_prompt)
    except LLMError:
        raise

    result = parse_report_response(raw)
    result.commits = commits
    result.since = since_label
    result.until = until_resolved
    result.author = author_filter
    result.truncated = truncated
    if not result.commit_count:
        result.commit_count = len(commits)
    return result


def render_report(
    result: ReportResult,
    console: Console | None = None,
    *,
    chinese: bool = False,
) -> None:
    console = console or Console()

    meta_bits = [f"{result.commit_count} commits"]
    if result.since:
        meta_bits.append(f"since {result.since}")
    if result.until:
        meta_bits.append(f"until {result.until}")
    if result.author:
        meta_bits.append(f"author {result.author}")
    console.print("[dim]" + " · ".join(meta_bits) + "[/dim]")

    if result.truncated:
        tip = (
            "警告：提交列表因过长被截断。"
            if chinese
            else "Warning: commit list was truncated before sending to the model."
        )
        console.print(f"[yellow]{tip}[/yellow]")

    if not result.parsed_ok:
        title = "原始模型输出（解析失败）" if chinese else "Raw model output (parse failed)"
        console.print(Panel(result.raw_text or "(empty)", title=title, border_style="red"))
        return

    if result.period_summary:
        title = "阶段摘要" if chinese else "Period summary"
        console.print(Panel(result.period_summary, title=title, border_style="blue"))

    if result.highlights:
        title = "重点工作" if chinese else "Highlights"
        bullets = "\n".join(f"• {h}" for h in result.highlights)
        console.print(Panel(bullets, title=title, border_style="cyan"))

    if result.categories:
        for cat in result.categories:
            if not cat.items:
                continue
            bullets = "\n".join(f"• {item}" for item in cat.items)
            console.print(Panel(bullets, title=cat.name, border_style="green"))

    if result.report_markdown:
        title = "可粘贴周报" if chinese else "Paste-ready report"
        console.print()
        console.print(f"[bold]{title}[/bold]")
        console.print(Markdown(result.report_markdown))
