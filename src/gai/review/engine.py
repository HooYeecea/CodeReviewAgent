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

from gai.common.config import Settings, load_settings
from gai.common.git import (
    StagedSnapshot,
    staged_snapshot,
    assert_staged_snapshot,
    count_staged_files,
    current_branch_name,
    get_staged_diff,
    has_staged_changes,
)
from gai.common.llm.client import LLMClient, LLMError
from gai.common.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from gai.common.llm.usage import set_llm_usage_meta

Severity = Literal["critical", "warning", "info"]

_SEVERITY_STYLE = {
    "critical": "bold red",
    "warning": "yellow",
    "info": "cyan",
}


class DiffTooLargeError(RuntimeError):
    """Staged diff exceeds ``max_diff_chars``; prefer ``gai splitflow``."""

    def __init__(self, *, chars: int, limit: int) -> None:
        self.chars = chars
        self.limit = limit
        super().__init__(
            f"Staged diff is too large ({chars} chars > limit {limit}). "
            "Use `gai splitflow` to review in coherent batches."
        )


@dataclass(frozen=True)
class StagedDiffInfo:
    """Full ignore-filtered staged diff plus size vs ``max_diff_chars``."""

    text: str
    chars: int
    limit: int
    exceeds: bool
    snapshot: StagedSnapshot | None = None
    scope: dict = field(default_factory=dict)

    def clipped(self) -> tuple[str, bool]:
        """Return ``(text, truncated)`` clipped to ``limit`` when needed."""
        if not self.exceeds:
            return self.text, False
        clipped = (
            self.text[: self.limit]
            + "\n\n... [diff truncated by gai due to size limit] ...\n"
        )
        return clipped, True


def load_staged_diff_info(
    *,
    settings: Settings | None = None,
) -> StagedDiffInfo:
    """Read staged diff once; reuse for size checks and review payloads."""
    settings = settings or load_settings()
    snapshot = staged_snapshot()
    diff, _ = get_staged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=None,
        snapshot=snapshot,
    )
    chars = len(diff)
    limit = settings.max_diff_chars
    return StagedDiffInfo(
        text=diff,
        chars=chars,
        limit=limit,
        exceeds=chars > limit,
        snapshot=snapshot,
    )


def staged_diff_size(
    *,
    settings: Settings | None = None,
) -> tuple[int, int, bool]:
    """Return ``(chars, limit, exceeds)`` for the current staged diff."""
    info = load_staged_diff_info(settings=settings)
    return info.chars, info.limit, info.exceeds


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
    snapshot: StagedSnapshot | None = None
    model: str = ""
    reviewed_at: str = ""
    scope: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review": [item.to_dict() for item in self.review],
            "commit_message": self.commit_message,
            "summary": self.summary,
            "parsed_ok": self.parsed_ok,
            "truncated_diff": self.truncated_diff,
            "status": "failed" if not self.parsed_ok else (
                "incomplete" if self.truncated_diff or self.coverage.get("state") in {"incomplete", "failed"}
                else ("issues" if self.review else "passed")),
            "scope": self.scope,
            "coverage": self.coverage or {"state": "failed" if not self.parsed_ok else (
                "incomplete" if self.truncated_diff else "complete")},
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

    def invalid() -> ReviewResult:
        return ReviewResult(raw_text=text, parsed_ok=False)

    raw_review = data.get("review")
    message = data.get("commit_message", data.get("commitMessage"))
    if (
        not isinstance(raw_review, list)
        or not isinstance(message, str)
        or not isinstance(data.get("summary", ""), str)
    ):
        return invalid()

    items: list[ReviewItem] = []
    if isinstance(raw_review, list):
        for entry in raw_review:
            if not isinstance(entry, dict):
                return invalid()
            severity = entry.get("severity")
            line = entry.get("line")
            if (
                not isinstance(severity, str)
                or severity.strip().lower() not in {
                    "critical", "error", "blocker", "high", "warning", "warn", "medium", "info"
                }
                or not isinstance(entry.get("file"), str)
                or not entry["file"].strip()
                or not isinstance(entry.get("issue"), str)
                or not entry["issue"].strip()
                or not isinstance(entry.get("suggestion", ""), str)
                or (line is not None and (
                    isinstance(line, bool) or not isinstance(line, (int, str))
                    or _normalize_line(line) is None
                ))
            ):
                return invalid()
            issue = entry["issue"].strip()
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
    allow_truncated: bool = False,
    diff_info: StagedDiffInfo | None = None,
    chunked: bool = False,
) -> ReviewResult:
    """Load staged diff and ask the LLM for review + commit message.

    When the staged diff exceeds ``max_diff_chars`` and ``allow_truncated`` is
    false, raises ``DiffTooLargeError`` so the CLI can offer ``gai splitflow``.

    Pass ``diff_info`` when the caller already loaded the staged diff (avoids a
    second git read when the process-local cache was cleared or key differs).
    """
    settings = settings or load_settings()

    branch_review = bool(diff_info and diff_info.scope.get("kind") == "branch")
    if not branch_review and not has_staged_changes():
        raise RuntimeError("No staged changes. Run `git add` first.")

    info = diff_info or load_staged_diff_info(settings=settings)
    from gai.review.branch import validate_scope
    validate_scope(info.scope)
    if info.snapshot is not None and not branch_review:
        assert_staged_snapshot(info.snapshot)
    if info.exceeds and not allow_truncated and not chunked:
        raise DiffTooLargeError(chars=info.chars, limit=info.limit)

    diff, truncated = (info.text, False) if chunked else info.clipped()
    if not diff.strip():
        if branch_review:
            raise RuntimeError("分支没有可审查改动，或全部被忽略 / No branch changes remain after ignore filters")
        raise RuntimeError(
            "Staged changes are empty after ignore filters. "
            "Adjust ignore_patterns or stage other files."
        )

    if message_only:
        action_detail = "commit-message"
    elif review_only:
        action_detail = "review"
    else:
        action_detail = "review+message"

    from gai.review.chunks import coverage, split_patch
    from gai.common.git import staged_name_status
    files = info.scope.get("files", []) if branch_review else [p for _, p in staged_name_status()]
    set_llm_usage_meta(
        action_detail=action_detail,
        branch=current_branch_name(),
        files_count=len(files),
        diff_chars=len(diff),
        truncated=truncated,
    )

    client = LLMClient(settings)
    system = SYSTEM_PROMPT
    if settings.review_rules:
        system += "\nRepository review requirements (do not change the JSON schema):\n" + "\n".join(settings.review_rules)
    pieces = split_patch(diff, info.limit) if chunked else [diff]
    results = []
    for piece in pieces:
        validate_scope(info.scope)
        if info.snapshot is not None and not branch_review:
            assert_staged_snapshot(info.snapshot)
        set_llm_usage_meta(diff_chars=len(piece))
        prompt = build_user_prompt(diff=piece, truncated=truncated, review_only=review_only,
                                   message_only=message_only, chinese=chinese)
        results.append(parse_review_response(client.chat(system=system, user=prompt)))
        if not results[-1].parsed_ok:
            break
    result = results[0]
    if len(pieces) > 1:
        result = ReviewResult(parsed_ok=len(results) == len(pieces) and all(r.parsed_ok for r in results),
                              summary="\n\n".join(r.summary for r in results))
        seen = set()
        for part in results:
            for item in part.review:
                key = (item.severity, item.file, item.line, item.issue)
                if key not in seen:
                    seen.add(key)
                    result.review.append(item)
    validate_scope(info.scope)
    if info.snapshot is not None and not branch_review:
        assert_staged_snapshot(info.snapshot)
    result.truncated_diff = truncated
    result.snapshot = info.snapshot
    from gai.review.archive import now
    result.model = settings.model
    result.reviewed_at = now()
    result.scope = info.scope
    result.coverage = coverage(info.text, min(info.chars, info.limit) if truncated else info.chars,
                               files, failed=not result.parsed_ok, parts=len(pieces))
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

    if result.coverage.get("state") == "incomplete" and not result.truncated_diff:
        console.print("[yellow]审查覆盖不完整：部分文件只有二进制元信息，需要人工检查。 / "
                      "Incomplete coverage: binary content needs manual review.[/yellow]")

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
