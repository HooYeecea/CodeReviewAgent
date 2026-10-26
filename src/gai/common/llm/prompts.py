"""LLM prompt templates."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are an expert code reviewer and commit-message writer working on local git diffs.

Your job:
1. Review the staged diff for bugs, memory leaks, performance issues, security risks, and logic errors.
2. Write a Conventional Commits message that accurately summarizes the change.

Rules:
- Base file paths and line hints ONLY on the provided diff hunks (new-file line numbers when possible).
- Keep findings concise and actionable. Prefer high-signal issues over style nits.
- If nothing concerning is found, return an empty "review" array.
- Commit message must follow Conventional Commits: type(scope): subject
  Types: feat, fix, refactor, perf, docs, test, chore, style, ci, build
- Subject: imperative mood, lowercase start preferred, no trailing period, <= 72 chars.
- Respond with ONLY valid JSON matching the schema. No markdown fences, no commentary.

JSON schema:
{
  "review": [
    {
      "severity": "critical" | "warning" | "info",
      "file": "path/to/file",
      "line": 123,
      "issue": "one-sentence problem",
      "suggestion": "one-sentence fix suggestion"
    }
  ],
  "commit_message": "type(scope): subject",
  "summary": "one short paragraph overview of the change"
}

"line" may be null when unknown. "summary" is optional but recommended.
"""


REPORT_SYSTEM_PROMPT = """\
You are an assistant that turns git commit history into a concise work report.

Your job:
1. Read the provided commit list (date, author, subject, optional shortstat).
2. Summarize what was accomplished in a form suitable for a weekly/daily work report.
3. Group related commits; ignore noise like trivial merge or empty chore when possible.
4. Do NOT invent work that is not supported by the commits.
5. When this is a team report (no single-author filter), include participant narratives.
6. When per-author detail is requested, fill `per_author` with concrete work per person.
7. Respond with ONLY valid JSON matching the schema. No markdown fences, no commentary.

JSON schema:
{
  "period_summary": "2-4 sentence overview of the work in this period",
  "highlights": ["key accomplishment 1", "key accomplishment 2"],
  "categories": [
    {
      "name": "Features" | "Bug fixes" | "Refactors" | "Docs/Tests" | "Chore/Infra" | "Other",
      "items": ["bullet point grounded in commits"]
    }
  ],
  "participants": [
    {
      "name": "Author Name",
      "email": "a@example.com",
      "commit_count": 5,
      "summary": "one-line contribution summary"
    }
  ],
  "per_author": [
    {
      "name": "Author Name",
      "email": "a@example.com",
      "highlights": ["what they shipped"],
      "items": ["more detailed bullets"]
    }
  ],
  "contributor_count": 3,
  "report_markdown": "a paste-ready work report in Markdown (sections + bullets)",
  "commit_count": 12
}

Rules for participants / per_author:
- `participants` is required for team reports; use empty array for single-author reports.
- `per_author` must be filled only when per-author detail is requested; otherwise use [].
- Prefer grounding names/emails in the commit list. commit_count should match the list.
- `report_markdown` should already include participant overview (and per-author sections when requested).
- `commit_count` / `contributor_count` should match the provided commits when possible.
Keep bullets concrete and outcome-oriented, not a raw dump of commit subjects.
"""


STAGE_SYSTEM_PROMPT = """\
You help a developer decide which local git changes to stage for the next commit.

Your job:
1. Read the working-tree status (and optional unstaged diff snippet).
2. Suggest a coherent set of paths to `git add` for ONE focused commit.
3. Prefer source/docs that belong together; usually exclude secrets, local env files,
   build artifacts, project ``.gai/`` runtime logs/reports, and unrelated WIP unless
   the status clearly shows they are part of this change.

Rules:
- Only suggest paths that appear in the provided status/diff.
- Never suggest paths under ``.gai/`` (local gai usage/history/report artifacts).
- Prefer concrete file paths over "." unless nearly everything should be staged.
- Respond with ONLY valid JSON. No markdown fences, no commentary.

JSON schema:
{
  "paths": ["path/to/file.py", "README.md"],
  "reason": "one short sentence explaining the staging choice"
}
"""


COMMIT_BATCH_SYSTEM_PROMPT = """\
You help a developer split a large dirty working tree into several focused git commits.

Your job:
1. Read the working-tree status (paths + optional diff snippet).
2. Propose an ordered list of commit batches. Each batch is one coherent commit.
3. Optimize for reviewability: each batch should be understandable on its own and
   small enough that a full review of that batch is feasible (prefer staying under
   the provided max_diff_chars budget when possible).
4. Split by theme / module / concern (e.g. core logic vs docs vs tests), NOT by
   blindly chopping the diff at a character limit.
5. Paths are file-level only (you cannot split hunks inside one file). Put each
   path in at most one batch.
6. Prefer covering all provided changed paths. If you intentionally leave WIP out,
   say so in `summary` and omit those paths.
7. Never put paths under ``.gai/`` into any batch (local gai runtime logs/reports).
8. Order batches so later commits can build on earlier ones when that matters.
9. Prefer 2–8 batches for a large tree; avoid one-file-per-batch unless necessary.
10. If the changes already form ONE coherent commit, return exactly one batch covering them.
   Only recommend multiple batches when themes/modules clearly diverge.
11. Respond with ONLY valid JSON. No markdown fences, no commentary.

JSON schema:
{
  "summary": "one short sentence describing the overall split plan",
  "batches": [
    {
      "title": "short batch title",
      "paths": ["path/to/file.py", "README.md"],
      "reason": "why these paths belong in one commit",
      "commit_message_en": "type(scope): optional english subject hint",
      "commit_message_cn": "type(scope): 可选中文说明"
    }
  ]
}
"""


BILINGUAL_MESSAGE_SYSTEM_PROMPT = """\
You write Conventional Commits messages for a staged git diff.

Your job:
1. Propose ONE English commit message.
2. Propose ONE Simplified Chinese commit message for the same change.
3. Both must follow Conventional Commits: type(scope): subject
   Types: feat, fix, refactor, perf, docs, test, chore, style, ci, build
4. Keep type/scope in English in BOTH messages.
5. English subject: imperative mood, lowercase start preferred, no trailing period, <= 72 chars.
6. Chinese subject: concise Simplified Chinese after the colon, no trailing period.
7. Respond with ONLY valid JSON. No markdown fences, no commentary.

JSON schema:
{
  "commit_message_en": "type(scope): english subject",
  "commit_message_cn": "type(scope): 中文说明"
}
"""


def build_stage_user_prompt(
    *,
    status_text: str,
    diff_snippet: str = "",
    truncated: bool = False,
    chinese: bool = False,
) -> str:
    notes: list[str] = []
    if truncated:
        notes.append("NOTE: The unstaged diff snippet was truncated due to size.")
    if chinese:
        notes.append("LANGUAGE: Write `reason` in Simplified Chinese.")
    else:
        notes.append("LANGUAGE: Write `reason` in English.")
    header = "\n".join(notes)
    body = (
        f"{header}\n\n"
        "Git status --porcelain follows:\n"
        "```\n"
        f"{status_text.strip() or '(empty)'}\n"
        "```\n"
    )
    if diff_snippet.strip():
        body += (
            "\nUnstaged / working-tree diff snippet (for context):\n"
            "```diff\n"
            f"{diff_snippet}\n"
            "```\n"
        )
    body += "\nProduce the JSON staging suggestion now."
    return body


def build_commit_batch_user_prompt(
    *,
    status_text: str,
    paths: list[str],
    diff_snippet: str = "",
    truncated: bool = False,
    max_diff_chars: int = 80_000,
    chinese: bool = False,
    message_lang: str | None = None,
    require_concrete_messages: bool = False,
) -> str:
    notes: list[str] = [
        f"CONSTRAINT: Prefer each batch's staged diff to fit under ~{max_diff_chars} characters.",
        "CONSTRAINT: Each path in at most one batch; use only paths from the list below.",
    ]
    if truncated:
        notes.append(
            "NOTE: The working-tree diff snippet was truncated due to size; "
            "rely more on path grouping and status."
        )
    if chinese:
        notes.append(
            "LANGUAGE: Write `summary`, each batch `title`, and `reason` in Simplified Chinese. "
            "Keep commit message type/scope in English."
        )
    else:
        notes.append("LANGUAGE: Write `summary`, `title`, and `reason` in English.")
    lang = (message_lang or "").strip().lower()
    if require_concrete_messages:
        if lang == "cn":
            notes.append(
                "REQUIRED: For EVERY batch fill `commit_message_cn` with a final "
                "Conventional Commits message the user can commit as-is "
                "(type(scope): 中文说明). Also fill `commit_message_en` if possible."
            )
        else:
            notes.append(
                "REQUIRED: For EVERY batch fill `commit_message_en` with a final "
                "Conventional Commits message the user can commit as-is "
                "(type(scope): english subject). Also fill `commit_message_cn` if possible."
            )
    header = "\n".join(notes)
    path_lines = "\n".join(f"- {p}" for p in paths) or "- (none)"
    body = (
        f"{header}\n\n"
        "Changed paths to cover:\n"
        f"{path_lines}\n\n"
        "Git status --porcelain follows:\n"
        "```\n"
        f"{status_text.strip() or '(empty)'}\n"
        "```\n"
    )
    if diff_snippet.strip():
        body += (
            "\nWorking-tree diff snippet (context only; may be incomplete):\n"
            "```diff\n"
            f"{diff_snippet}\n"
            "```\n"
        )
    body += "\nProduce the JSON commit-batch plan now."
    return body


def build_bilingual_message_user_prompt(
    *,
    diff: str,
    truncated: bool = False,
) -> str:
    note = ""
    if truncated:
        note = (
            "NOTE: The diff was truncated due to size. "
            "Summarize what is present.\n\n"
        )
    return (
        f"{note}"
        "Staged git diff follows. Produce both commit messages now.\n\n"
        "```diff\n"
        f"{diff}\n"
        "```"
    )


def build_user_prompt(
    *,
    diff: str,
    truncated: bool = False,
    review_only: bool = False,
    message_only: bool = False,
    chinese: bool = False,
) -> str:
    mode_notes: list[str] = []
    if truncated:
        mode_notes.append(
            "NOTE: The diff was truncated due to size. Review what is present; "
            "mention that coverage may be incomplete in summary if needed."
        )
    if review_only:
        mode_notes.append(
            "Focus on code review. Still include a reasonable commit_message."
        )
    if message_only:
        mode_notes.append(
            "Focus on generating the commit_message. review may be an empty array."
        )
    if chinese:
        mode_notes.append(
            "LANGUAGE: Write `issue`, `suggestion`, and `summary` in Simplified Chinese. "
            "Keep `severity` enum values in English (critical/warning/info). "
            "Keep Conventional Commits `type`/`scope` in English; "
            "the commit subject after the colon may be Simplified Chinese."
        )

    notes = "\n".join(mode_notes)
    header = notes + ("\n\n" if notes else "")
    return (
        f"{header}"
        "Staged git diff follows. Produce the JSON response now.\n\n"
        "```diff\n"
        f"{diff}\n"
        "```"
    )


def build_report_user_prompt(
    *,
    commits_text: str,
    since: str | None = None,
    until: str | None = None,
    author: str | None = None,
    commit_count: int = 0,
    contributor_count: int = 0,
    participants_text: str = "",
    truncated: bool = False,
    chinese: bool = False,
    team_mode: bool = False,
    per_author: bool = False,
    period_label: str | None = None,
) -> str:
    meta: list[str] = [f"Commit count provided: {commit_count}"]
    if contributor_count:
        meta.append(f"Contributor count: {contributor_count}")
    if period_label:
        meta.append(f"Report period (must mention in report_markdown): {period_label}")
    if since:
        meta.append(f"Since query: {since}")
    if until:
        meta.append(f"Until: {until}")
    if author:
        meta.append(f"Author filter: {author}")
        meta.append("MODE: single-author report. Leave participants/per_author empty arrays.")
    elif team_mode:
        meta.append("MODE: team report. Fill participants with every contributor.")
        if per_author:
            meta.append(
                "PER-AUTHOR: required. Fill per_author with concrete work for each person."
            )
        else:
            meta.append(
                "PER-AUTHOR: not requested. Set per_author to []. "
                "Still include a short summary per participant."
            )
    if participants_text:
        meta.append("Local participant stats (trust commit counts):\n" + participants_text)
    if truncated:
        meta.append(
            "NOTE: The commit list was truncated due to size; "
            "summarize what is present and mention possible incompleteness."
        )
    if chinese:
        meta.append(
            "LANGUAGE: Write period_summary, highlights, category names, "
            "category items, participant summaries, per_author text, "
            "and report_markdown in Simplified Chinese. "
            "report_markdown should be ready to paste into a Chinese work report "
            "and must state the concrete period dates."
        )

    header = "\n".join(meta)
    return (
        f"{header}\n\n"
        "Commit list follows. Produce the JSON work report now.\n\n"
        f"{commits_text}\n"
    )
