"""Work-report engine: summarize git commit history via LLM."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

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
class ParticipantStat:
    name: str
    email: str
    commit_count: int
    share: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "commit_count": self.commit_count,
            "share": self.share,
            "summary": self.summary,
        }


@dataclass
class PerAuthorSection:
    name: str
    email: str
    highlights: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "highlights": list(self.highlights),
            "items": list(self.items),
        }


@dataclass
class ReportResult:
    period_summary: str = ""
    highlights: list[str] = field(default_factory=list)
    categories: list[ReportCategory] = field(default_factory=list)
    participants: list[ParticipantStat] = field(default_factory=list)
    per_author: list[PerAuthorSection] = field(default_factory=list)
    contributor_count: int = 0
    report_markdown: str = ""
    commit_count: int = 0
    commits: list[CommitInfo] = field(default_factory=list)
    since: str | None = None
    until: str | None = None
    author: str | None = None
    team_mode: bool = False
    per_author_requested: bool = False
    raw_text: str = ""
    parsed_ok: bool = True
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_summary": self.period_summary,
            "highlights": list(self.highlights),
            "categories": [c.to_dict() for c in self.categories],
            "participants": [p.to_dict() for p in self.participants],
            "per_author": [p.to_dict() for p in self.per_author],
            "contributor_count": self.contributor_count,
            "report_markdown": self.report_markdown,
            "commit_count": self.commit_count,
            "since": self.since,
            "until": self.until,
            "author": self.author,
            "team_mode": self.team_mode,
            "per_author_requested": self.per_author_requested,
            "parsed_ok": self.parsed_ok,
            "truncated": self.truncated,
            "commits": [c.to_dict() for c in self.commits],
        }


def collect_participant_stats(commits: list[CommitInfo]) -> list[ParticipantStat]:
    """Aggregate local commit counts by author email (fallback: name)."""
    if not commits:
        return []

    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    emails: dict[str, str] = {}
    for c in commits:
        key = (c.author_email or c.author_name or "unknown").strip().lower()
        counts[key] += 1
        names.setdefault(key, c.author_name or key)
        emails.setdefault(key, c.author_email or "")

    total = sum(counts.values()) or 1
    stats = [
        ParticipantStat(
            name=names[key],
            email=emails[key],
            commit_count=count,
            share=round(100.0 * count / total, 1),
        )
        for key, count in counts.most_common()
    ]
    return stats


def format_participants_for_prompt(stats: list[ParticipantStat]) -> str:
    lines = []
    for p in stats:
        email = p.email or "-"
        lines.append(
            f"- {p.name} <{email}>: {p.commit_count} commits ({p.share}%)"
        )
    return "\n".join(lines)


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


def _parse_participants(raw: Any) -> list[ParticipantStat]:
    if not isinstance(raw, list):
        return []
    out: list[ParticipantStat] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        try:
            count = int(entry.get("commit_count") or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            share = float(entry.get("share") or 0)
        except (TypeError, ValueError):
            share = 0.0
        out.append(
            ParticipantStat(
                name=name,
                email=str(entry.get("email") or "").strip(),
                commit_count=count,
                share=share,
                summary=str(entry.get("summary") or "").strip(),
            )
        )
    return out


def _parse_per_author(raw: Any) -> list[PerAuthorSection]:
    if not isinstance(raw, list):
        return []
    out: list[PerAuthorSection] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        highlights_raw = entry.get("highlights") or []
        items_raw = entry.get("items") or []
        highlights = (
            [str(x).strip() for x in highlights_raw if str(x).strip()]
            if isinstance(highlights_raw, list)
            else []
        )
        items = (
            [str(x).strip() for x in items_raw if str(x).strip()]
            if isinstance(items_raw, list)
            else []
        )
        out.append(
            PerAuthorSection(
                name=name,
                email=str(entry.get("email") or "").strip(),
                highlights=highlights,
                items=items,
            )
        )
    return out


def _merge_participant_stats(
    local: list[ParticipantStat],
    from_model: list[ParticipantStat],
) -> list[ParticipantStat]:
    """Prefer local counts; attach model summaries when emails/names match."""
    if not local:
        return from_model

    by_email = {
        (p.email or "").strip().lower(): p for p in from_model if p.email
    }
    by_name = {p.name.strip().lower(): p for p in from_model if p.name}

    merged: list[ParticipantStat] = []
    for base in local:
        match = None
        email_key = (base.email or "").strip().lower()
        if email_key and email_key in by_email:
            match = by_email[email_key]
        else:
            match = by_name.get(base.name.strip().lower())
        merged.append(
            ParticipantStat(
                name=base.name,
                email=base.email,
                commit_count=base.commit_count,
                share=base.share,
                summary=(match.summary if match else "") or "",
            )
        )
    return merged


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
    highlights = (
        [str(x).strip() for x in highlights_raw if str(x).strip()]
        if isinstance(highlights_raw, list)
        else []
    )

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

    contributor_count = data.get("contributor_count")
    try:
        contributor_count_int = int(contributor_count) if contributor_count is not None else 0
    except (TypeError, ValueError):
        contributor_count_int = 0

    return ReportResult(
        period_summary=str(data.get("period_summary") or "").strip(),
        highlights=highlights,
        categories=categories,
        participants=_parse_participants(data.get("participants")),
        per_author=_parse_per_author(data.get("per_author")),
        contributor_count=contributor_count_int,
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
    per_author: bool = False,
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

    team_mode = author_filter is None
    # --per only meaningful for team reports
    per_author_mode = bool(per_author) and team_mode

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

    local_participants = collect_participant_stats(commits) if team_mode else []
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
        contributor_count=len(local_participants),
        participants_text=format_participants_for_prompt(local_participants),
        truncated=truncated,
        chinese=chinese,
        team_mode=team_mode,
        per_author=per_author_mode,
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
    result.team_mode = team_mode
    result.per_author_requested = per_author_mode
    result.truncated = truncated
    if not result.commit_count:
        result.commit_count = len(commits)

    if team_mode:
        result.participants = _merge_participant_stats(
            local_participants,
            result.participants,
        )
        result.contributor_count = len(result.participants)
        if not per_author_mode:
            result.per_author = []
    else:
        result.participants = []
        result.per_author = []
        result.contributor_count = 1

    return result


def build_export_markdown(result: ReportResult, *, chinese: bool = False) -> str:
    """Build a complete Markdown document for file export."""
    lines: list[str] = []
    title = "工作报告" if chinese else "Work Report"
    lines.append(f"# {title}")
    lines.append("")

    meta: list[str] = []
    if result.since:
        meta.append(f"- since: `{result.since}`")
    if result.until:
        meta.append(f"- until: `{result.until}`")
    if result.author:
        meta.append(f"- author: `{result.author}`")
    meta.append(f"- commits: **{result.commit_count}**")
    if result.team_mode:
        meta.append(f"- contributors: **{result.contributor_count}**")
    lines.extend(meta)
    lines.append("")

    if result.period_summary:
        lines.append(f"## {'阶段摘要' if chinese else 'Period summary'}")
        lines.append("")
        lines.append(result.period_summary)
        lines.append("")

    if result.team_mode and result.participants:
        lines.append(f"## {'参与者' if chinese else 'Participants'}")
        lines.append("")
        lines.append(
            "| "
            + ("姓名" if chinese else "Name")
            + " | Email | "
            + ("提交数" if chinese else "Commits")
            + " | "
            + ("占比" if chinese else "Share")
            + " | "
            + ("简述" if chinese else "Summary")
            + " |"
        )
        lines.append("| --- | --- | ---: | ---: | --- |")
        for p in result.participants:
            summary = p.summary.replace("|", "\\|") if p.summary else ""
            lines.append(
                f"| {p.name} | {p.email or '-'} | {p.commit_count} | {p.share}% | {summary} |"
            )
        lines.append("")

    if result.highlights:
        lines.append(f"## {'重点工作' if chinese else 'Highlights'}")
        lines.append("")
        for h in result.highlights:
            lines.append(f"- {h}")
        lines.append("")

    if result.categories:
        lines.append(f"## {'分类' if chinese else 'Categories'}")
        lines.append("")
        for cat in result.categories:
            if not cat.items:
                continue
            lines.append(f"### {cat.name}")
            lines.append("")
            for item in cat.items:
                lines.append(f"- {item}")
            lines.append("")

    if result.per_author_requested and result.per_author:
        lines.append(f"## {'按人明细' if chinese else 'Per author'}")
        lines.append("")
        for section in result.per_author:
            header = section.name
            if section.email:
                header = f"{section.name} <{section.email}>"
            lines.append(f"### {header}")
            lines.append("")
            for h in section.highlights:
                lines.append(f"- {h}")
            for item in section.items:
                lines.append(f"- {item}")
            lines.append("")

    if result.report_markdown:
        lines.append(f"## {'完整文稿' if chinese else 'Full draft'}")
        lines.append("")
        lines.append(result.report_markdown.strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def resolve_report_output_path(
    out: str,
    *,
    cwd: Path | None = None,
) -> tuple[Path, str | None]:
    """Resolve --out path. On invalid parent dir, fall back to cwd + warning."""
    cwd = cwd or Path.cwd()
    raw = out.strip().strip('"').strip("'")
    if not raw:
        raise ValueError("output path is empty")

    path = Path(raw).expanduser()
    warning: str | None = None
    today = date.today().isoformat()
    default_name = f"gai-report-{today}.md"

    # Directory target (existing dir, or trailing slash/backslash)
    looks_like_dir = raw.endswith(("/", "\\")) or (path.exists() and path.is_dir())

    if looks_like_dir:
        target_dir = path
        filename = default_name
        if not target_dir.exists():
            warning = f"Directory not found: {target_dir}. Falling back to current directory."
            return (cwd / filename).resolve(), warning
        return (target_dir / filename).resolve(), warning

    # File path
    if path.suffix == "":
        path = path.with_suffix(".md")

    if path.is_absolute():
        parent = path.parent
        if not parent.exists():
            warning = f"Directory not found: {parent}. Falling back to current directory."
            return (cwd / path.name).resolve(), warning
        return path.resolve(), warning

    # Relative file: ensure parent under cwd exists
    candidate = (cwd / path).resolve()
    parent = candidate.parent
    if not parent.exists():
        warning = f"Directory not found: {parent}. Falling back to current directory."
        return (cwd / path.name).resolve(), warning
    return candidate, warning


def export_report(
    result: ReportResult,
    out: str,
    *,
    chinese: bool = False,
    cwd: Path | None = None,
) -> tuple[Path, str | None]:
    """Write Markdown report to disk. Returns (path, optional warning)."""
    target, warning = resolve_report_output_path(out, cwd=cwd)
    content = build_export_markdown(result, chinese=chinese)
    target.write_text(content, encoding="utf-8")
    return target, warning


def render_report(
    result: ReportResult,
    console: Console | None = None,
    *,
    chinese: bool = False,
) -> None:
    console = console or Console()

    meta_bits = [f"{result.commit_count} commits"]
    if result.team_mode:
        meta_bits.append(f"{result.contributor_count} contributors")
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

    if result.team_mode and result.participants:
        table = Table(
            title="参与者" if chinese else "Participants",
            show_lines=True,
        )
        table.add_column("姓名" if chinese else "Name", overflow="fold")
        table.add_column("Email", overflow="fold")
        table.add_column("提交" if chinese else "Commits", justify="right")
        table.add_column("占比" if chinese else "Share", justify="right")
        table.add_column("简述" if chinese else "Summary", overflow="fold")
        for p in result.participants:
            table.add_row(
                p.name,
                p.email or "-",
                str(p.commit_count),
                f"{p.share}%",
                p.summary or "-",
            )
        console.print(table)

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

    if result.per_author_requested and result.per_author:
        for section in result.per_author:
            title = section.name
            if section.email:
                title = f"{section.name} <{section.email}>"
            bullets = "\n".join(
                f"• {x}" for x in (section.highlights + section.items) if x
            ) or ("（无明细）" if chinese else "(no details)")
            console.print(Panel(bullets, title=title, border_style="magenta"))

    if result.report_markdown:
        title = "可粘贴周报" if chinese else "Paste-ready report"
        console.print()
        console.print(f"[bold]{title}[/bold]")
        console.print(Markdown(result.report_markdown))
