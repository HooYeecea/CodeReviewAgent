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
) -> str:
    meta: list[str] = [f"Commit count provided: {commit_count}"]
    if contributor_count:
        meta.append(f"Contributor count: {contributor_count}")
    if since:
        meta.append(f"Since: {since}")
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
            "report_markdown should be ready to paste into a Chinese work report."
        )

    header = "\n".join(meta)
    return (
        f"{header}\n\n"
        "Commit list follows. Produce the JSON work report now.\n\n"
        f"{commits_text}\n"
    )
