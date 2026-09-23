"""Code review engine: call LLM, parse structured result, render."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gai.config import Settings, load_settings
from gai.git_ops import get_staged_diff, has_staged_changes
from gai.llm.client import LLMClient, LLMError
from gai.llm.prompts import SYSTEM_PROMPT, build_user_prompt

Severity = Literal["critical", "warning", "info"]

_SEVERITY_STYLE = {
    "critical": "bold red",
    "warning": "yellow",
    "info": "cyan",
}


@dataclass
class ReviewItem:
    severity: Severity
    file: str
    line: int | None
    issue: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewResult:
    review: list[ReviewItem] = field(default_factory=list)
    commit_message: str = ""
    summary: str = ""
    raw_text: str = ""
    parsed_ok: bool = True
    truncated_diff: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "review": [item.to_dict() for item in self.review],
            "commit_message": self.commit_message,
            "summary": self.summary,
            "parsed_ok": self.parsed_ok,
            "truncated_diff": self.truncated_diff,
        }


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_blob(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None

    fence = _JSON_FENCE.search(text)
    if fence:
        return fence.group(1).strip()

    # Find outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return None


def _normalize_severity(value: Any) -> Severity:
    s = str(value or "info").strip().lower()
    if s in ("critical", "error", "blocker", "high"):
        return "critical"
    if s in ("warning", "warn", "medium"):
        return "warning"
    return "info"


def _normalize_line(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def parse_review_response(text: str) -> ReviewResult:
    """Parse model output into ReviewResult; degrade gracefully on failure."""
    blob = _extract_json_blob(text)
    if not blob:
        return ReviewResult(
            commit_message="",
            summary=text.strip()[:2000],
            raw_text=text,
            parsed_ok=False,
        )

    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return ReviewResult(
            commit_message="",
            summary=text.strip()[:2000],
            raw_text=text,
            parsed_ok=False,
        )

    if not isinstance(data, dict):
        return ReviewResult(raw_text=text, parsed_ok=False, summary=str(data)[:2000])

    items: list[ReviewItem] = []
    raw_review = data.get("review") or []
    if isinstance(raw_review, list):
        for entry in raw_review:
            if not isinstance(entry, dict):
                continue
            issue = str(entry.get("issue") or "").strip()
            if not issue:
                continue
            items.append(
                ReviewItem(
                    severity=_normalize_severity(entry.get("severity")),
                    file=str(entry.get("file") or "").strip() or "(unknown)",
                    line=_normalize_line(entry.get("line")),
                    issue=issue,
                    suggestion=str(entry.get("suggestion") or "").strip(),
                )
            )

    commit_message = str(data.get("commit_message") or data.get("commitMessage") or "").strip()
    summary = str(data.get("summary") or "").strip()

    return ReviewResult(
        review=items,
        commit_message=commit_message,
        summary=summary,
        raw_text=text,
        parsed_ok=True,
    )


def run_review(
    *,
    settings: Settings | None = None,
    message_only: bool = False,
    review_only: bool = False,
    chinese: bool = False,
) -> ReviewResult:
    """Load staged diff and ask the LLM for review + commit message."""
    settings = settings or load_settings()

    if not has_staged_changes():
        raise RuntimeError("No staged changes. Run `git add` first.")

    diff, truncated = get_staged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=settings.max_diff_chars,
    )
    if not diff.strip():
        raise RuntimeError(
            "Staged changes are empty after ignore filters. "
            "Adjust ignore_patterns or stage other files."
        )

    client = LLMClient(settings)
    user_prompt = build_user_prompt(
        diff=diff,
        truncated=truncated,
        review_only=review_only,
        message_only=message_only,
        chinese=chinese,
    )

    try:
        raw = client.chat(system=SYSTEM_PROMPT, user=user_prompt)
    except LLMError:
        raise

    result = parse_review_response(raw)
    result.truncated_diff = truncated
    return result


def render_review(
    result: ReviewResult,
    console: Console | None = None,
    *,
    chinese: bool = False,
) -> None:
    console = console or Console()

    if result.truncated_diff:
        if chinese:
            console.print(
                "[yellow]警告：[/yellow] Diff 因过长被截断后才发送给模型。"
            )
        else:
            console.print(
                "[yellow]Warning:[/yellow] Diff was truncated before sending to the model."
            )

    if result.summary:
        title = "摘要" if chinese else "Summary"
        console.print(Panel(result.summary, title=title, border_style="blue"))

    if not result.parsed_ok:
        title = "原始模型输出（解析失败）" if chinese else "Raw model output (parse failed)"
        empty = "（空）" if chinese else "(empty)"
        console.print(
            Panel(
                result.raw_text or empty,
                title=title,
                border_style="red",
            )
        )
        return

    if not result.review:
        if chinese:
            console.print("[green]审查未发现明显问题。[/green]")
        else:
            console.print("[green]No issues found by the reviewer.[/green]")
        return

    table = Table(title="代码审查" if chinese else "Code Review", show_lines=True)
    if chinese:
        table.add_column("严重度", style="bold", width=10)
        table.add_column("位置", overflow="fold")
        table.add_column("问题", overflow="fold")
        table.add_column("建议", overflow="fold")
    else:
        table.add_column("Sev", style="bold", width=10)
        table.add_column("Location", overflow="fold")
        table.add_column("Issue", overflow="fold")
        table.add_column("Suggestion", overflow="fold")

    order = {"critical": 0, "warning": 1, "info": 2}
    for item in sorted(result.review, key=lambda x: order.get(x.severity, 9)):
        loc = item.file
        if item.line is not None:
            loc = f"{item.file}:{item.line}"
        sev = Text(item.severity, style=_SEVERITY_STYLE.get(item.severity, ""))
        table.add_row(sev, loc, item.issue, item.suggestion or "-")

    console.print(table)
    if chinese:
        console.print("[dim]行号仅供参考（来自 diff），并非静态分析结果。[/dim]")
    else:
        console.print(
            "[dim]Line numbers are advisory (derived from the diff), not static analysis.[/dim]"
        )
