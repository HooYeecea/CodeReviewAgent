"""Shared helpers for ``gai devflow`` (stage suggest + bilingual commit messages)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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
    STAGE_SYSTEM_PROMPT,
    build_bilingual_message_user_prompt,
    build_stage_user_prompt,
)
from gai.llm.usage import set_llm_usage_meta
from gai.review import _extract_json_blob


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


def suggest_bilingual_messages(
    *,
    settings: Settings | None = None,
) -> BilingualMessages:
    """Ask the LLM for English + Chinese Conventional Commit messages."""
    settings = settings or load_settings()
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
