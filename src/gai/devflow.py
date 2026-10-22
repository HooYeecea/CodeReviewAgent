"""Compatibility shim — implementation lives in ``gai.flow.devflow``."""

from __future__ import annotations

from gai.flow.devflow import (
    BilingualMessages,
    CommitBatch,
    CommitBatchPlan,
    StageSuggestion,
    apply_message_lang_to_batches,
    fallback_commit_batches,
    list_staged_paths,
    normalize_commit_batches,
    normalize_path_input,
    parse_bilingual_messages,
    parse_commit_batch_plan,
    parse_stage_suggestion,
    stageable_paths_summary,
    suggest_bilingual_messages,
    suggest_commit_batches,
    suggest_stage_paths,
)

__all__ = [
    "BilingualMessages",
    "CommitBatch",
    "CommitBatchPlan",
    "StageSuggestion",
    "apply_message_lang_to_batches",
    "fallback_commit_batches",
    "list_staged_paths",
    "normalize_commit_batches",
    "normalize_path_input",
    "parse_bilingual_messages",
    "parse_commit_batch_plan",
    "parse_stage_suggestion",
    "stageable_paths_summary",
    "suggest_bilingual_messages",
    "suggest_commit_batches",
    "suggest_stage_paths",
]
