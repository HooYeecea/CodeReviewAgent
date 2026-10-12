"""Shared helpers for ``gai devflow`` / ``gai splitflow``."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from gai.config import Settings, load_settings
from gai.git_ops import (
    ChangeEntry,
    current_branch_name,
    get_staged_diff,
    get_unstaged_diff,
    list_change_entries,
    porcelain_status,
)
from gai.llm.client import LLMClient, LLMError
from gai.llm.prompts import (
    BILINGUAL_MESSAGE_SYSTEM_PROMPT,
    COMMIT_BATCH_SYSTEM_PROMPT,
    STAGE_SYSTEM_PROMPT,
    build_bilingual_message_user_prompt,
    build_commit_batch_user_prompt,
    build_stage_user_prompt,
)
from gai.llm.usage import set_llm_usage_meta
from gai.review import DiffTooLargeError, _extract_json_blob, staged_diff_size


@dataclass(frozen=True)
class StageSuggestion:
    paths: list[str]
    reason: str
    raw_text: str = ""
    parsed_ok: bool = True


@dataclass(frozen=True)
class BilingualMessages:
    message_en: str
    message_cn: str
    raw_text: str = ""
    parsed_ok: bool = True


@dataclass(frozen=True)
class CommitBatch:
    title: str
    paths: list[str]
    reason: str
    message_hint_en: str = ""
    message_hint_cn: str = ""


@dataclass(frozen=True)
class CommitBatchPlan:
    batches: list[CommitBatch]
    summary: str
    raw_text: str = ""
    parsed_ok: bool = True


def parse_stage_suggestion(text: str) -> StageSuggestion:
    blob = _extract_json_blob(text) or text.strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return StageSuggestion(paths=[], reason="", raw_text=text, parsed_ok=False)
    if not isinstance(data, dict):
        return StageSuggestion(paths=[], reason="", raw_text=text, parsed_ok=False)
    raw_paths = data.get("paths") or []
    paths: list[str] = []
    if isinstance(raw_paths, list):
        for item in raw_paths:
            p = str(item or "").strip().strip('"')
            if p and p not in paths:
                paths.append(p)
    reason = str(data.get("reason") or "").strip()
    return StageSuggestion(
        paths=paths,
        reason=reason,
        raw_text=text,
        parsed_ok=bool(paths),
    )


def parse_bilingual_messages(text: str) -> BilingualMessages:
    blob = _extract_json_blob(text) or text.strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return BilingualMessages(
            message_en="", message_cn="", raw_text=text, parsed_ok=False
        )
    if not isinstance(data, dict):
        return BilingualMessages(
            message_en="", message_cn="", raw_text=text, parsed_ok=False
        )
    en = str(
        data.get("commit_message_en")
        or data.get("message_en")
        or data.get("commit_message")
        or ""
    ).strip()
    cn = str(
        data.get("commit_message_cn")
        or data.get("message_cn")
        or ""
    ).strip()
    return BilingualMessages(
        message_en=en,
        message_cn=cn,
        raw_text=text,
        parsed_ok=bool(en or cn),
    )


def suggest_stage_paths(
    *,
    settings: Settings | None = None,
    chinese: bool = False,
) -> StageSuggestion:
    """Ask the LLM which paths to stage from the current working tree."""
    settings = settings or load_settings()
    status = porcelain_status().strip()
    if not status:
        raise RuntimeError("Working tree is clean; nothing to stage.")

    entries = list_change_entries()
    stageable = [
        e.path
        for e in entries
        if e.untracked or e.unstaged or (e.staged and e.unstaged)
    ]
    # Also allow suggesting already-partially-changed files.
    if not stageable:
        stageable = [e.path for e in entries]

    diff, truncated = get_unstaged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=min(settings.max_diff_chars, 24_000),
    )
    set_llm_usage_meta(
        action_detail="stage-suggest",
        branch=current_branch_name(),
        files_count=len(entries),
        diff_chars=len(diff),
        truncated=truncated,
    )
    client = LLMClient(settings)
    try:
        raw = client.chat(
            system=STAGE_SYSTEM_PROMPT,
            user=build_stage_user_prompt(
                status_text=status,
                diff_snippet=diff,
                truncated=truncated,
                chinese=chinese,
            ),
        )
    except LLMError:
        raise

    suggestion = parse_stage_suggestion(raw)
    if not suggestion.parsed_ok:
        # Fallback: suggest all stageable paths if model parse fails.
        return StageSuggestion(
            paths=stageable or ["."],
            reason=(
                "模型输出无法解析，已回退为当前全部可暂存路径。"
                if chinese
                else "Could not parse model output; falling back to all stageable paths."
            ),
            raw_text=raw,
            parsed_ok=False,
        )

    allowed = {e.path for e in entries}
    filtered = [p for p in suggestion.paths if p == "." or p in allowed]
    if not filtered:
        filtered = stageable or ["."]
    return StageSuggestion(
        paths=filtered,
        reason=suggestion.reason,
        raw_text=suggestion.raw_text,
        parsed_ok=suggestion.parsed_ok,
    )


def parse_commit_batch_plan(text: str) -> CommitBatchPlan:
    blob = _extract_json_blob(text) or text.strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return CommitBatchPlan(batches=[], summary="", raw_text=text, parsed_ok=False)
    if not isinstance(data, dict):
        return CommitBatchPlan(batches=[], summary="", raw_text=text, parsed_ok=False)
    summary = str(data.get("summary") or "").strip()
    raw_batches = data.get("batches") or []
    batches: list[CommitBatch] = []
    if isinstance(raw_batches, list):
        for item in raw_batches:
            if not isinstance(item, dict):
                continue
            raw_paths = item.get("paths") or []
            paths: list[str] = []
            if isinstance(raw_paths, list):
                for p in raw_paths:
                    path = str(p or "").strip().strip('"')
                    if path and path not in paths:
                        paths.append(path)
            if not paths:
                continue
            title = str(item.get("title") or "").strip() or f"batch-{len(batches) + 1}"
            reason = str(item.get("reason") or "").strip()
            en = str(
                item.get("commit_message_en")
                or item.get("message_en")
                or item.get("commit_message")
                or ""
            ).strip()
            cn = str(
                item.get("commit_message_cn") or item.get("message_cn") or ""
            ).strip()
            batches.append(
                CommitBatch(
                    title=title,
                    paths=paths,
                    reason=reason,
                    message_hint_en=en,
                    message_hint_cn=cn,
                )
            )
    return CommitBatchPlan(
        batches=batches,
        summary=summary,
        raw_text=text,
        parsed_ok=bool(batches),
    )


def _stageable_paths(entries: list[ChangeEntry] | None = None) -> list[str]:
    items = entries if entries is not None else list_change_entries()
    paths: list[str] = []
    for e in items:
        if e.path and e.path not in paths:
            # Include anything changed (staged / unstaged / untracked).
            if e.untracked or e.unstaged or e.staged:
                paths.append(e.path)
    return paths


def fallback_commit_batches(
    paths: list[str],
    *,
    chinese: bool = False,
    max_files_per_batch: int = 12,
) -> list[CommitBatch]:
    """Group paths by top-level directory when the model plan is unusable."""
    groups: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        key = PurePosixPath(path.replace("\\", "/")).parts[0] if path else "."
        groups[key].append(path)

    batches: list[CommitBatch] = []
    for key in sorted(groups.keys()):
        chunk = groups[key]
        for i in range(0, len(chunk), max_files_per_batch):
            part = chunk[i : i + max_files_per_batch]
            suffix = f" ({i // max_files_per_batch + 1})" if len(chunk) > max_files_per_batch else ""
            title = (
                f"{key} 相关改动{suffix}"
                if chinese
                else f"{key} changes{suffix}"
            )
            reason = (
                f"按目录 {key} 回退分组（模型计划不可用或未覆盖全部路径）。"
                if chinese
                else f"Fallback grouping by directory `{key}`."
            )
            batches.append(CommitBatch(title=title, paths=part, reason=reason))
    return batches


def normalize_commit_batches(
    batches: list[CommitBatch],
    *,
    allowed_paths: list[str],
    chinese: bool = False,
) -> list[CommitBatch]:
    """Drop unknown/duplicate paths; append leftovers as a final batch."""
    allowed = set(allowed_paths)
    seen: set[str] = set()
    out: list[CommitBatch] = []
    for batch in batches:
        paths: list[str] = []
        for path in batch.paths:
            if path not in allowed or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        if not paths:
            continue
        out.append(
            CommitBatch(
                title=batch.title,
                paths=paths,
                reason=batch.reason,
                message_hint_en=batch.message_hint_en,
                message_hint_cn=batch.message_hint_cn,
            )
        )
    leftover = [p for p in allowed_paths if p not in seen]
    if leftover:
        out.append(
            CommitBatch(
                title=("其余改动" if chinese else "Remaining changes"),
                paths=leftover,
                reason=(
                    "未包含在前述批次中的剩余路径。"
                    if chinese
                    else "Paths not covered by earlier batches."
                ),
            )
        )
    return out


def suggest_commit_batches(
    *,
    settings: Settings | None = None,
    chinese: bool = False,
) -> CommitBatchPlan:
    """Ask the LLM to split the dirty tree into coherent commit batches."""
    settings = settings or load_settings()
    status = porcelain_status().strip()
    if not status:
        raise RuntimeError("Working tree is clean; nothing to split.")

    entries = list_change_entries()
    paths = _stageable_paths(entries)
    if not paths:
        raise RuntimeError("No changed paths found to split into commits.")

    # Planning prompt can use a smaller snippet; path list carries the structure.
    diff, truncated = get_unstaged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=min(settings.max_diff_chars, 32_000),
    )
    # Include staged content too when the index is already dirty.
    staged_diff, staged_truncated = get_staged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=min(settings.max_diff_chars, 16_000),
    )
    if staged_diff.strip():
        diff = (staged_diff + "\n\n" + diff).strip()
        truncated = truncated or staged_truncated
        if len(diff) > min(settings.max_diff_chars, 32_000):
            limit = min(settings.max_diff_chars, 32_000)
            diff = (
                diff[:limit]
                + "\n\n... [diff truncated by gai due to size limit] ...\n"
            )
            truncated = True

    set_llm_usage_meta(
        action_detail="commit-batch-plan",
        branch=current_branch_name(),
        files_count=len(paths),
        diff_chars=len(diff),
        truncated=truncated,
    )
    client = LLMClient(settings)
    raw = client.chat(
        system=COMMIT_BATCH_SYSTEM_PROMPT,
        user=build_commit_batch_user_prompt(
            status_text=status,
            paths=paths,
            diff_snippet=diff,
            truncated=truncated,
            max_diff_chars=settings.max_diff_chars,
            chinese=chinese,
        ),
    )
    plan = parse_commit_batch_plan(raw)
    if not plan.parsed_ok:
        batches = fallback_commit_batches(paths, chinese=chinese)
        return CommitBatchPlan(
            batches=batches,
            summary=(
                "模型输出无法解析，已按目录回退分组。"
                if chinese
                else "Could not parse model output; fell back to directory groups."
            ),
            raw_text=raw,
            parsed_ok=False,
        )

    batches = normalize_commit_batches(
        plan.batches, allowed_paths=paths, chinese=chinese
    )
    if not batches:
        batches = fallback_commit_batches(paths, chinese=chinese)
        return CommitBatchPlan(
            batches=batches,
            summary=(
                "模型批次为空，已按目录回退分组。"
                if chinese
                else "Model returned no usable batches; fell back to directory groups."
            ),
            raw_text=raw,
            parsed_ok=False,
        )
    return CommitBatchPlan(
        batches=batches,
        summary=plan.summary,
        raw_text=plan.raw_text,
        parsed_ok=plan.parsed_ok,
    )


def suggest_bilingual_messages(
    *,
    settings: Settings | None = None,
    allow_truncated: bool = False,
) -> BilingualMessages:
    """Ask the LLM for English + Chinese Conventional Commit messages."""
    settings = settings or load_settings()
    chars, limit, exceeds = staged_diff_size(settings=settings)
    if exceeds and not allow_truncated:
        raise DiffTooLargeError(chars=chars, limit=limit)
    diff, truncated = get_staged_diff(
        ignore_patterns=settings.ignore_patterns,
        max_chars=settings.max_diff_chars,
    )
    if not diff.strip():
        raise RuntimeError(
            "Staged changes are empty after ignore filters. "
            "Adjust ignore_patterns or stage other files."
        )
    set_llm_usage_meta(
        action_detail="commit-message-bilingual",
        branch=current_branch_name(),
        files_count=len(list_change_entries()),
        diff_chars=len(diff),
        truncated=truncated,
    )
    client = LLMClient(settings)
    raw = client.chat(
        system=BILINGUAL_MESSAGE_SYSTEM_PROMPT,
        user=build_bilingual_message_user_prompt(diff=diff, truncated=truncated),
    )
    return parse_bilingual_messages(raw)


def normalize_path_input(text: str) -> list[str]:
    """Split user path input on whitespace / commas."""
    parts = re.split(r"[\s,;]+", (text or "").strip())
    out: list[str] = []
    for p in parts:
        item = p.strip().strip('"').strip("'")
        if item and item not in out:
            out.append(item)
    return out


def stageable_paths_summary(
    entries: list[ChangeEntry] | None = None,
) -> dict[str, list[str]]:
    """Group change entries for CLI display."""
    items = entries if entries is not None else list_change_entries()
    untracked = [e.path for e in items if e.untracked]
    unstaged = [e.path for e in items if e.unstaged and not e.untracked]
    staged = [e.path for e in items if e.staged]
    return {"untracked": untracked, "unstaged": unstaged, "staged": staged}
