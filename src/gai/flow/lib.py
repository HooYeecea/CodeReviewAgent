"""Shared helpers for gai splitflow / devflow commands."""

from __future__ import annotations

import re
from typing import Optional

import typer
from rich.prompt import Confirm, Prompt

from gai.cli_common import (
    _print_error,
    _print_llm_usage,
    _print_step_trace,
    _print_trace,
    console,
    err_console,
)
from gai.flow.devflow import (
    CommitBatch,
    CommitBatchPlan,
    normalize_path_input,
    sanitize_commit_batches,
    stageable_paths_summary,
    suggest_bilingual_messages,
    suggest_commit_batches,
    suggest_stage_paths,
)
from gai.common.git import (
    StagedSnapshot,
    assert_staged_snapshot,
    GitError,
    add as git_add,
    commit as git_commit,
    get_traced_commands,
    has_staged_changes,
    is_worktree_dirty,
    list_change_entries,
    short_status,
    unadd as git_unadd,
)
from gai.common.llm.client import LLMError
from gai.review import (
    DiffTooLargeError,
    load_staged_diff_info,
    render_review,
    run_review,
    staged_diff_size,
)

from gai.review.helpers import (
    _maybe_suggest_optional_splitflow,
    _offer_splitflow_instead,
)
from gai.sync.push_pull import _do_push

def _print_batch_plan(
    batches: list[CommitBatch],
    *,
    summary: str,
    chinese: bool,
    label_prefix: str = "",
    show_concrete_message: bool = False,
) -> None:
    if summary:
        label = "拆分概要：" if chinese else "Plan summary:"
        console.print(f"[bold]{label}[/bold] {summary}")
    for idx, batch in enumerate(batches, start=1):
        tag = f"{label_prefix}{idx}" if label_prefix else str(idx)
        console.print(
            f"\n[bold cyan]#{tag}[/bold cyan] {batch.title} "
            f"[dim]({len(batch.paths)} files)[/dim]"
        )
        if batch.reason:
            console.print(f"  [dim]{batch.reason}[/dim]")
        console.print("  " + " ".join(batch.paths))
        if show_concrete_message and batch.commit_message:
            msg_label = "提交词：" if chinese else "Commit message:"
            console.print(f"  [bold]{msg_label}[/bold] {batch.commit_message}")
        else:
            hints = [h for h in (batch.message_hint_en, batch.message_hint_cn) if h]
            if hints:
                console.print("  [dim]→ " + " | ".join(hints) + "[/dim]")


def _review_language(*, chinese: bool) -> bool:
    if chinese:
        return True
    lang = Prompt.ask("Review language [cn/en]", default="en").strip().lower()
    return lang in {"cn", "zh", "chinese", "中文"}


def _run_staged_review(
    *,
    chinese: bool,
    review_cn: bool,
    flush,
    allow_truncated: bool = False,
    offer_splitflow: bool = False,
    suggest_split: bool = False,
    remote: str | None = None,
    trace: bool = False,
    auto_continue: bool = False,
) -> StagedSnapshot | None:
    """Return the reviewed snapshot, or None when the user stops."""
    diff_info = load_staged_diff_info()
    if offer_splitflow and not allow_truncated:
        if diff_info.exceeds:
            _offer_splitflow_instead(
                chinese=chinese,
                remote=remote,
                trace=trace,
                interactive=True,
                chars=diff_info.chars,
                limit=diff_info.limit,
            )
        elif suggest_split:
            _maybe_suggest_optional_splitflow(
                chinese=chinese, remote=remote, trace=trace, interactive=True
            )
    status_text = "正在调用大模型审查..." if chinese else "Calling LLM for code review..."
    with console.status(f"[bold]{status_text}[/bold]"):
        result = run_review(
            review_only=True,
            chinese=review_cn,
            allow_truncated=allow_truncated,
            diff_info=diff_info,
        )
    render_review(result, console, chinese=review_cn)
    flush("review")
    if not result.parsed_ok:
        raise LLMError("Review output failed validation; commit stopped", kind="bad_response")
    if diff_info.snapshot is None:
        raise RuntimeError("Missing reviewed index snapshot")
    if auto_continue:
        return diff_info.snapshot
    cont = Confirm.ask(
        "审查完成，继续选择提交信息？"
        if chinese
        else "Review done. Continue to commit message?",
        default=True,
    )
    if not cont:
        console.print("已取消。" if chinese else "Aborted.")
        return None
    return diff_info.snapshot


def _commit_fixed_message(
    message: str,
    *,
    chinese: bool,
    flush,
    expected_snapshot: StagedSnapshot,
    confirm: bool = True,
) -> bool:
    """Commit with a preselected message. Returns False if aborted."""
    text = (message or "").strip()
    if not text:
        tip = "提交信息为空，已跳过。" if chinese else "Empty commit message; skipped."
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("commit")
        return False
    label = "将使用的提交信息：" if chinese else "Commit message to use:"
    console.print(f"[bold]{label}[/bold] {text}")
    if confirm and not Confirm.ask(
        "确认提交？" if chinese else "Confirm commit?",
        default=True,
    ):
        console.print("已取消提交。" if chinese else "Commit aborted.")
        flush("commit")
        return False
    git_commit(text, expected_snapshot=expected_snapshot)
    console.print(
        ("[green]已提交：[/green] " if chinese else "[green]Committed:[/green] ")
        + text
    )
    flush("commit")
    return True


def _print_level2_plan(
    batches: list[CommitBatch],
    *,
    parent_idx: int,
    parent_title: str,
    summary: str,
    chinese: bool,
    message_lang: str,
) -> None:
    lang_tag = ("中文" if message_lang == "cn" else "英文") if chinese else message_lang.upper()
    console.print(
        (
            f"\n[yellow]一级 #{parent_idx}「{parent_title}」Diff 仍过大，"
            f"拆成 {len(batches)} 个二级批次（提交词语言：{lang_tag}）：[/yellow]"
            if chinese
            else (
                f"\n[yellow]Level-1 #{parent_idx} '{parent_title}' is still too large; "
                f"splitting into {len(batches)} level-2 batches "
                f"(message language: {lang_tag}):[/yellow]"
            )
        )
    )
    _print_batch_plan(
        batches,
        summary=summary,
        chinese=chinese,
        label_prefix=f"{parent_idx}.",
        show_concrete_message=True,
    )


def _normalize_msg_lang(token: str) -> str | None:
    t = (token or "").strip().lower()
    if t in {"en", "english", "e", "英", "英文"}:
        return "en"
    if t in {"cn", "zh", "chinese", "c", "中", "中文"}:
        return "cn"
    return None


def parse_batch_message_lang_spec(text: str, n: int) -> list[str] | None:
    """Parse ``en,cn,en`` or ``1=en,2=cn`` into ``n`` language codes."""
    raw = (text or "").strip()
    if not raw or n <= 0:
        return None
    # Form: 1=en,2=cn  /  1:en 2:cn
    if "=" in raw or ":" in raw:
        out = [""] * n
        parts = re.split(r"[\s,;]+", raw)
        for part in parts:
            if not part:
                continue
            if "=" in part:
                left, right = part.split("=", 1)
            elif ":" in part:
                left, right = part.split(":", 1)
            else:
                return None
            if not left.strip().isdigit():
                return None
            idx = int(left.strip())
            lang = _normalize_msg_lang(right)
            if lang is None or not (1 <= idx <= n):
                return None
            out[idx - 1] = lang
        if any(not x for x in out):
            return None
        return out
    # Form: en,cn,en
    parts = [p for p in re.split(r"[\s,;]+", raw) if p]
    if len(parts) != n:
        return None
    out = []
    for part in parts:
        lang = _normalize_msg_lang(part)
        if lang is None:
            return None
        out.append(lang)
    return out


def _ask_splitflow_message_langs(
    batches: list[CommitBatch],
    *,
    chinese: bool,
) -> list[str]:
    """Ask once: all-EN / all-CN / per-batch message language."""
    n = len(batches)
    console.print(
        "[bold]提交词语言策略：[/bold]"
        if chinese
        else "[bold]Commit message language:[/bold]"
    )
    console.print(
        "  [cyan]1[/cyan]) "
        + ("全部英文" if chinese else "All English")
    )
    console.print(
        "  [cyan]2[/cyan]) "
        + ("全部中文" if chinese else "All Chinese")
    )
    console.print(
        "  [cyan]3[/cyan]) "
        + ("按批次指定" if chinese else "Per-batch")
    )
    default = "2" if chinese else "1"
    choice = Prompt.ask(
        "请选择" if chinese else "Choose",
        default=default,
    ).strip().lower()

    if choice in {"1", "en", "e", "all-en", "全部英文", "英文"}:
        langs = ["en"] * n
    elif choice in {"2", "cn", "zh", "c", "all-cn", "全部中文", "中文"}:
        langs = ["cn"] * n
    elif choice in {"3", "mix", "m", "per", "按批", "按批次", "按批次指定"}:
        langs = _ask_per_batch_message_langs(batches, chinese=chinese)
    else:
        # Allow direct specs like "en,cn,en" or "all en"
        if choice in {"all en", "allen", "全部 en"}:
            langs = ["en"] * n
        elif choice in {"all cn", "allcn", "全部 cn"}:
            langs = ["cn"] * n
        else:
            parsed = parse_batch_message_lang_spec(choice, n)
            if parsed is None:
                tip = "无效选择，已回退为按批次指定。" if chinese else "Invalid choice; falling back to per-batch."
                err_console.print(f"[yellow]{tip}[/yellow]")
                langs = _ask_per_batch_message_langs(batches, chinese=chinese)
            else:
                langs = parsed

    # Show summary
    bits = []
    for i, lang in enumerate(langs, start=1):
        tag = ("中文" if lang == "cn" else "英文") if chinese else lang.upper()
        bits.append(f"#{i}:{tag}")
    console.print(
        ("[dim]已设定：[/dim] " if chinese else "[dim]Set:[/dim] ") + " ".join(bits)
    )
    return langs


def _ask_per_batch_message_langs(
    batches: list[CommitBatch],
    *,
    chinese: bool,
) -> list[str]:
    n = len(batches)
    tip = (
        f"可一次输入，例如：en,cn,en  或  1=en,2=cn,3=en（共 {n} 批）；"
        "直接回车则逐批询问。"
        if chinese
        else f"One-shot e.g. en,cn,en or 1=en,2=cn,3=en ({n} batches); "
        "press Enter to answer per batch."
    )
    console.print(f"[dim]{tip}[/dim]")
    one_shot = Prompt.ask(
        "批量指定（可留空）" if chinese else "Bulk spec (optional)",
        default="",
    ).strip()
    if one_shot:
        parsed = parse_batch_message_lang_spec(one_shot, n)
        if parsed is not None:
            return parsed
        err_console.print(
            "[yellow]格式无效，改为逐批询问。[/yellow]"
            if chinese
            else "[yellow]Invalid format; asking per batch.[/yellow]"
        )

    langs: list[str] = []
    default_lang = "cn" if chinese else "en"
    for idx, batch in enumerate(batches, start=1):
        console.print(f"[cyan]#{idx}[/cyan] {batch.title}")
        answer = Prompt.ask(
            (
                f"批次 {idx} 提交词语言 [en/cn]"
                if chinese
                else f"Batch {idx} message language [en/cn]"
            ),
            default=default_lang,
        )
        lang = _normalize_msg_lang(answer) or default_lang
        langs.append(lang)
    return langs


def _pick_and_commit_message(
    *,
    chinese: bool,
    flush,
    expected_snapshot: StagedSnapshot,
    hint_en: str = "",
    hint_cn: str = "",
    allow_truncated: bool = False,
    prefer_lang: str | None = None,
) -> bool:
    """Generate bilingual message choices and commit. Returns False if aborted."""
    assert_staged_snapshot(expected_snapshot)
    status_text = (
        "正在生成中英提交信息..."
        if chinese
        else "Generating English + Chinese commit messages..."
    )
    with console.status(f"[bold]{status_text}[/bold]"):
        messages = suggest_bilingual_messages(allow_truncated=allow_truncated)

    options: list[tuple[str, str]] = []
    en = messages.message_en or hint_en
    cn_msg = messages.message_cn or hint_cn
    if en:
        options.append(("en", en))
    if cn_msg:
        options.append(("cn", cn_msg))

    prefer = _normalize_msg_lang(prefer_lang or "") if prefer_lang else None
    commit_message = ""

    def _choose_from_menu() -> str:
        if not options:
            tip = (
                "未能解析中英提交信息，请手动输入。"
                if chinese
                else "Could not parse bilingual messages; enter one manually."
            )
            err_console.print(f"[yellow]{tip}[/yellow]")
            return Prompt.ask(
                "请输入提交信息" if chinese else "Enter commit message"
            ).strip()
        console.print(
            "[bold]可选提交信息：[/bold]" if chinese else "[bold]Commit message choices:[/bold]"
        )
        default_choice = "1"
        for idx, (lang, text) in enumerate(options, start=1):
            tag = "英文" if lang == "en" else "中文"
            if not chinese:
                tag = "EN" if lang == "en" else "CN"
            console.print(f"  [cyan]{idx}[/cyan]) [{tag}] {text}")
            if prefer and lang == prefer:
                default_choice = str(idx)
        custom_n = len(options) + 1
        console.print(
            f"  [cyan]{custom_n}[/cyan]) "
            + ("手动输入" if chinese else "Type a custom message")
        )
        choice = Prompt.ask(
            "请选择" if chinese else "Choose",
            default=default_choice,
        ).strip()
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(options):
                return options[n - 1][1]
            if n == custom_n:
                return Prompt.ask(
                    "请输入提交信息" if chinese else "Enter commit message"
                ).strip()
        if choice and not choice.isdigit():
            return choice
        tip = "无效选择。" if chinese else "Invalid choice."
        err_console.print(f"[red]{tip}[/red]")
        flush("commit")
        raise typer.Exit(code=1)

    if prefer and options:
        by_lang = {lang: text for lang, text in options}
        if prefer in by_lang:
            commit_message = by_lang[prefer]
            tag = ("中文" if prefer == "cn" else "英文") if chinese else prefer.upper()
            console.print(
                (
                    f"[dim]本批按预设使用{tag}提交词。[/dim]"
                    if chinese
                    else f"[dim]Using preset {tag} message for this batch.[/dim]"
                )
            )
        else:
            tip = (
                f"本批缺少{('中文' if prefer == 'cn' else '英文')}提交词，请手动选择。"
                if chinese
                else f"No {prefer.upper()} message for this batch; choose manually."
            )
            err_console.print(f"[yellow]{tip}[/yellow]")
            commit_message = _choose_from_menu()
    else:
        commit_message = _choose_from_menu()

    if not commit_message:
        tip = "提交信息为空，已取消。" if chinese else "Empty commit message; aborted."
        err_console.print(f"[red]{tip}[/red]")
        flush("commit")
        raise typer.Exit(code=1)

    label = "将使用的提交信息：" if chinese else "Commit message to use:"
    console.print(f"[bold]{label}[/bold] {commit_message}")
    if not Confirm.ask(
        "确认提交？" if chinese else "Confirm commit?",
        default=True,
    ):
        if prefer:
            tip = (
                "改选手动选择本批提交词？"
                if chinese
                else "Pick a different message for this batch?"
            )
            if Confirm.ask(tip, default=True):
                commit_message = _choose_from_menu()
                if not commit_message:
                    flush("commit")
                    raise typer.Exit(code=1)
                console.print(f"[bold]{label}[/bold] {commit_message}")
                if not Confirm.ask(
                    "确认提交？" if chinese else "Confirm commit?",
                    default=True,
                ):
                    console.print("已取消提交。" if chinese else "Commit aborted.")
                    flush("commit")
                    return False
            else:
                console.print("已取消提交。" if chinese else "Commit aborted.")
                flush("commit")
                return False
        else:
            console.print("已取消提交。" if chinese else "Commit aborted.")
            flush("commit")
            return False

    git_commit(commit_message, expected_snapshot=expected_snapshot)
    console.print(
        ("[green]已提交：[/green] " if chinese else "[green]Committed:[/green] ")
        + commit_message
    )
    flush("commit")
    return True


def _run_splitflow(
    *,
    chinese: bool,
    remote: str | None,
    trace: bool = False,
    plan: CommitBatchPlan | None = None,
) -> None:
    """Plan coherent commit batches, then review→commit each; optional push at end."""
    step = lambda n, title: console.print(
        f"\n[bold cyan]━━ {n}. {title} ━━[/bold cyan]"
    )
    flush = lambda label: _print_step_trace(trace=trace, chinese=chinese, step=label)

    step(0, "拆分计划 (plan)" if chinese else "Split plan")
    if not is_worktree_dirty() and not has_staged_changes():
        tip = (
            "工作区干净，没有可拆分的变更。"
            if chinese
            else "Working tree is clean; nothing to split."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("plan")
        raise typer.Exit(code=1)

    status = short_status()
    if status:
        console.print("[dim]" + status + "[/dim]")

    if has_staged_changes():
        tip = (
            "检测到已有暂存内容。分批流程会先清空暂存区，再按批次重新暂存。"
            if chinese
            else "Staged changes detected. Splitflow will unstage everything first, then re-stage per batch."
        )
        console.print(f"[yellow]{tip}[/yellow]")
        if not Confirm.ask(
            "确认清空暂存区并继续？" if chinese else "Unstage all and continue?",
            default=True,
        ):
            console.print("已取消。" if chinese else "Aborted.")
            flush("plan")
            raise typer.Exit(code=0)
        git_unadd(["."])
        console.print(
            "[green]已清空暂存区。[/green]" if chinese else "[green]Index cleared.[/green]"
        )

    reused_plan = plan is not None and bool(plan.batches)
    if reused_plan:
        console.print(
            "[dim]沿用刚才的分批建议。[/dim]"
            if chinese
            else "[dim]Reusing the suggested batch plan.[/dim]"
        )
        assert plan is not None
    else:
        status_text = (
            "正在让 AI 按主题拆分 commit 边界..."
            if chinese
            else "Asking AI to split coherent commit batches..."
        )
        with console.status(f"[bold]{status_text}[/bold]"):
            plan = suggest_commit_batches(chinese=chinese)

        if not plan.parsed_ok:
            console.print(
                f"[yellow]{plan.summary}[/yellow]"
                if plan.summary
                else (
                    "[yellow]模型计划不可用，已使用回退分组。[/yellow]"
                    if chinese
                    else "[yellow]Model plan unavailable; using fallback groups.[/yellow]"
                )
            )

    assert plan is not None
    cleaned = sanitize_commit_batches(plan.batches)
    if len(cleaned) != len(plan.batches):
        plan = CommitBatchPlan(
            batches=cleaned,
            summary=plan.summary,
            raw_text=plan.raw_text,
            parsed_ok=plan.parsed_ok and bool(cleaned),
        )
    if not plan.batches:
        tip = (
            "分批计划为空（可提交路径均被忽略或属于本地 .gai/）。"
            if chinese
            else "Batch plan is empty (paths are ignored or under local .gai/)."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("plan")
        raise typer.Exit(code=1)
    if not reused_plan:
        _print_batch_plan(plan.batches, summary=plan.summary, chinese=chinese)
        if not Confirm.ask(
            f"按以上 {len(plan.batches)} 个批次依次审查并提交？"
            if chinese
            else f"Proceed with these {len(plan.batches)} batches (review+commit each)?",
            default=True,
        ):
            console.print("已取消。" if chinese else "Aborted.")
            flush("plan")
            raise typer.Exit(code=0)
    else:
        _print_batch_plan(plan.batches, summary=plan.summary, chinese=chinese)

    message_langs = _ask_splitflow_message_langs(plan.batches, chinese=chinese)
    flush("plan")

    review_cn = _review_language(chinese=chinese)
    committed = 0
    total = len(plan.batches)

    for idx, batch in enumerate(plan.batches, start=1):
        prefer_lang = message_langs[idx - 1]
        step(
            idx,
            (
                f"一级批次 {idx}/{total}：{batch.title}"
                if chinese
                else f"Level-1 batch {idx}/{total}: {batch.title}"
            ),
        )
        console.print("[dim]" + " ".join(batch.paths) + "[/dim]")

        if has_staged_changes():
            git_unadd(["."])
        git_add(batch.paths)
        if not has_staged_changes():
            tip = (
                "本批次暂存后仍为空，已跳过。"
                if chinese
                else "Nothing staged for this batch; skipped."
            )
            err_console.print(f"[yellow]{tip}[/yellow]")
            flush(f"batch-{idx}-add")
            continue
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
        flush(f"batch-{idx}-add")

        _, _, exceeds = staged_diff_size()
        if exceeds and len(batch.paths) >= 2:
            # Level-2 re-split (max depth 2): unstage, plan, confirm once, auto-run.
            git_unadd(["."])
            status_text = (
                "一级批次仍过大，正在拆二级批次并生成提交词..."
                if chinese
                else "Level-1 batch still too large; planning level-2 batches + messages..."
            )
            with console.status(f"[bold]{status_text}[/bold]"):
                l2_plan = suggest_commit_batches(
                    chinese=chinese,
                    paths=list(batch.paths),
                    message_lang=prefer_lang,
                    require_concrete_messages=True,
                )
            if len(l2_plan.batches) < 2:
                # Cannot usefully split further; fall back to truncated single batch.
                tip = (
                    "无法再拆成多个二级批次，将对本一级批次继续（可能截断审查）。"
                    if chinese
                    else "Could not split into multiple level-2 batches; continuing this level-1 batch (review may truncate)."
                )
                console.print(f"[yellow]{tip}[/yellow]")
                git_add(batch.paths)
                reviewed_snapshot = _run_staged_review(
                    chinese=chinese,
                    review_cn=review_cn,
                    flush=flush,
                    allow_truncated=True,
                )
                if reviewed_snapshot is None:
                    raise typer.Exit(code=0)
                if not _pick_and_commit_message(
                    expected_snapshot=reviewed_snapshot,
                    chinese=chinese,
                    flush=flush,
                    hint_en=batch.message_hint_en,
                    hint_cn=batch.message_hint_cn,
                    allow_truncated=True,
                    prefer_lang=prefer_lang,
                ):
                    raise typer.Exit(code=0)
                committed += 1
                continue

            _print_level2_plan(
                l2_plan.batches,
                parent_idx=idx,
                parent_title=batch.title,
                summary=l2_plan.summary,
                chinese=chinese,
                message_lang=prefer_lang,
            )
            if not Confirm.ask(
                (
                    f"确认按以上 {len(l2_plan.batches)} 个二级批次依次审查并提交？"
                    if chinese
                    else f"Confirm these {len(l2_plan.batches)} level-2 batches (review+commit each)?"
                ),
                default=True,
            ):
                console.print(
                    "[yellow]已跳过该一级批次。[/yellow]"
                    if chinese
                    else "[yellow]Skipped this level-1 batch.[/yellow]"
                )
                flush(f"batch-{idx}-l2-skip")
                continue

            for j, sub in enumerate(l2_plan.batches, start=1):
                step(
                    f"{idx}.{j}",
                    (
                        f"二级 {idx}.{j}/{len(l2_plan.batches)}：{sub.title}"
                        if chinese
                        else f"Level-2 {idx}.{j}/{len(l2_plan.batches)}: {sub.title}"
                    ),
                )
                console.print("[dim]" + " ".join(sub.paths) + "[/dim]")
                if sub.commit_message:
                    console.print(
                        (
                            f"[dim]提交词：{sub.commit_message}[/dim]"
                            if chinese
                            else f"[dim]Message: {sub.commit_message}[/dim]"
                        )
                    )
                if has_staged_changes():
                    git_unadd(["."])
                git_add(sub.paths)
                if not has_staged_changes():
                    tip = (
                        "该二级批次暂存后为空，已跳过。"
                        if chinese
                        else "Nothing staged for this level-2 batch; skipped."
                    )
                    err_console.print(f"[yellow]{tip}[/yellow]")
                    flush(f"batch-{idx}-{j}-add")
                    continue
                flush(f"batch-{idx}-{j}-add")
                # Max depth 2: allow truncated review; no per-batch confirms.
                reviewed_snapshot = _run_staged_review(
                    chinese=chinese,
                    review_cn=review_cn,
                    flush=flush,
                    allow_truncated=True,
                    auto_continue=True,
                )
                if reviewed_snapshot is None:
                    raise typer.Exit(code=0)
                if not _commit_fixed_message(
                    sub.commit_message,
                    expected_snapshot=reviewed_snapshot,
                    chinese=chinese,
                    flush=flush,
                    confirm=False,
                ):
                    raise typer.Exit(code=0)
                committed += 1
            continue

        # Level-1 fits (or single oversized path): review + pick message.
        reviewed_snapshot = _run_staged_review(
            chinese=chinese,
            review_cn=review_cn,
            flush=flush,
            allow_truncated=True,
        )
        if reviewed_snapshot is None:
            raise typer.Exit(code=0)

        if not _pick_and_commit_message(
            expected_snapshot=reviewed_snapshot,
            chinese=chinese,
            flush=flush,
            hint_en=batch.message_hint_en,
            hint_cn=batch.message_hint_cn,
            allow_truncated=True,
            prefer_lang=prefer_lang,
        ):
            raise typer.Exit(code=0)
        committed += 1

    if committed == 0:
        tip = (
            "没有产生任何提交。"
            if chinese
            else "No commits were created."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("push")
        raise typer.Exit(code=1)

    step(total + 1, "推送 (push)" if chinese else "Push")
    tip = (
        f"已完成本地提交 {committed} 个。"
        if chinese
        else f"Created {committed} local commit(s)."
    )
    console.print(tip)
    if not Confirm.ask(
        "确认推送到远程？" if chinese else "Push to remote?",
        default=True,
    ):
        console.print(
            "已跳过推送。提交已保留在本地。"
            if chinese
            else "Push skipped. Commit(s) kept locally."
        )
        flush("push")
        raise typer.Exit(code=0)

    _do_push(remote=remote, yes=True, chinese=chinese)
    flush("push")


def _run_devflow(
    *,
    chinese: bool,
    remote: str | None,
    trace: bool = False,
    suggest_split: bool = False,
) -> None:
    """Interactive add → review → commit → push pipeline."""
    step = lambda n, title: console.print(
        f"\n[bold cyan]━━ {n}. {title} ━━[/bold cyan]"
    )
    flush = lambda label: _print_step_trace(trace=trace, chinese=chinese, step=label)

    # ----- 1) ADD (AI suggest) -----
    step(1, "暂存 (add)" if chinese else "Stage (add)")
    if not is_worktree_dirty():
        tip = (
            "工作区干净，没有可暂存或可提交的变更。"
            if chinese
            else "Working tree is clean; nothing to stage or commit."
        )
        err_console.print(f"[yellow]{tip}[/yellow]")
        flush("add")
        raise typer.Exit(code=1)

    entries = list_change_entries()
    groups = stageable_paths_summary(entries)
    status = short_status()
    if status:
        console.print("[dim]" + status + "[/dim]")

    need_stage = bool(groups["untracked"] or groups["unstaged"])
    if need_stage:
        status_text = (
            "正在让 AI 建议暂存路径..."
            if chinese
            else "Asking AI which paths to stage..."
        )
        with console.status(f"[bold]{status_text}[/bold]"):
            suggestion = suggest_stage_paths(chinese=chinese)

        reason_label = "建议理由：" if chinese else "Why:"
        paths_label = "建议暂存：" if chinese else "Suggested paths:"
        console.print(f"[bold]{paths_label}[/bold] {' '.join(suggestion.paths)}")
        if suggestion.reason:
            console.print(f"[dim]{reason_label} {suggestion.reason}[/dim]")
        hint = (
            "快捷键：y=采纳 AI 建议 · .=全部暂存 · n=手输路径"
            if chinese
            else "Shortcuts: y=accept AI · .=stage all · n=edit paths"
        )
        console.print(f"[dim]{hint}[/dim]")

        choice = Prompt.ask(
            (
                "暂存方式 [y / . / n]"
                if chinese
                else "Stage how? [y / . / n]"
            ),
            default="y",
        ).strip().lower()
        if choice in {"y", "yes"}:
            targets = suggestion.paths
        elif choice in {".", "all", "*"}:
            targets = ["."]
        elif choice in {"n", "no", "e", "edit"}:
            manual = Prompt.ask(
                (
                    "请输入要暂存的路径（空格/逗号分隔；输入 . 表示全部）"
                    if chinese
                    else "Paths to stage (space/comma separated; . for all)"
                ),
                default=" ".join(suggestion.paths),
            ).strip()
            targets = normalize_path_input(manual) or suggestion.paths
        else:
            # Allow typing paths / "." directly at the first prompt.
            targets = normalize_path_input(choice) or suggestion.paths
        if not targets:
            tip = "未选择任何路径，已取消。" if chinese else "No paths selected; aborted."
            err_console.print(f"[red]{tip}[/red]")
            flush("add")
            raise typer.Exit(code=1)

        git_add(targets)
        msg = (
            f"已暂存：{' '.join(targets)}"
            if chinese
            else f"Staged: {' '.join(targets)}"
        )
        console.print(f"[green]{msg}[/green]")
        status = short_status()
        if status:
            console.print("[dim]" + status + "[/dim]")
    else:
        tip = (
            "没有未暂存变更，将使用当前暂存区继续。"
            if chinese
            else "Nothing new to stage; continuing with the current index."
        )
        console.print(f"[dim]{tip}[/dim]")

    if not has_staged_changes():
        tip = (
            "暂存区仍为空，无法继续审查/提交。"
            if chinese
            else "Nothing staged; cannot continue to review/commit."
        )
        err_console.print(f"[red]{tip}[/red]")
        flush("add")
        raise typer.Exit(code=1)

    flush("add")

    # ----- 2) REVIEW -----
    step(2, "代码审查 (review)" if chinese else "Code review")
    review_cn = _review_language(chinese=chinese)
    reviewed_snapshot = _run_staged_review(
        chinese=chinese,
        review_cn=review_cn,
        flush=flush,
        offer_splitflow=True,
        suggest_split=suggest_split,
        remote=remote,
        trace=trace,
    )
    if reviewed_snapshot is None:
        raise typer.Exit(code=0)

    # ----- 3) COMMIT (bilingual choice) -----
    step(3, "提交 (commit)" if chinese else "Commit")
    if not _pick_and_commit_message(
        chinese=chinese, flush=flush, expected_snapshot=reviewed_snapshot,
    ):
        raise typer.Exit(code=0)

    # ----- 4) PUSH -----
    step(4, "推送 (push)" if chinese else "Push")
    if not Confirm.ask(
        "确认推送到远程？" if chinese else "Push to remote?",
        default=True,
    ):
        console.print(
            "已跳过推送。提交已保留在本地。"
            if chinese
            else "Push skipped. Commit kept locally."
        )
        flush("push")
        raise typer.Exit(code=0)

    _do_push(remote=remote, yes=True, chinese=chinese)
    flush("push")

