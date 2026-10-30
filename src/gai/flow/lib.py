"""Shared helpers for gai splitflow / devflow commands."""

from __future__ import annotations

import re
import json
from dataclasses import asdict
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
    BilingualMessages,
    StageSuggestion,
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
    parse_review_response,
    run_review,
    staged_diff_size,
)

from gai.review.helpers import (
    _maybe_suggest_optional_splitflow,
    _offer_splitflow_instead,
)
from gai.sync.push_pull import _do_push
from gai.flow.session import current_session

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
    session = current_session()
    key = session.cache_key("review", chinese=review_cn, truncated=allow_truncated) if session else ""
    cached = session.batch.get("review") if session else None
    if session:
        session.verify()
    if cached and cached["key"] == key:
        result = parse_review_response(json.dumps(cached["result"]))
        result.truncated_diff = cached["result"].get("truncated_diff", False)
        console.print("复用已保存的审查结果 / Reusing saved review", markup=False)
    else:
        if session:
            for field in ("review", "messages", "selected_message"):
                session.batch.pop(field, None)
            session.save()
        status_text = "正在调用大模型审查..." if chinese else "Calling LLM for code review..."
        with console.status(f"[bold]{status_text}[/bold]"):
            result = run_review(
                review_only=True, chinese=review_cn, allow_truncated=allow_truncated,
                diff_info=diff_info,
            )
        if session:
            session.verify()
            if result.parsed_ok:
                session.batch["review"] = {"key": key, "result": result.to_dict()}
                session.save()
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
    _flow_commit(text, expected_snapshot)
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
    yes: bool = False,
) -> bool:
    """Generate bilingual message choices and commit. Returns False if aborted."""
    assert_staged_snapshot(expected_snapshot)
    status_text = (
        "正在生成中英提交信息..."
        if chinese
        else "Generating English + Chinese commit messages..."
    )
    session = current_session()
    key = session.cache_key("messages", truncated=allow_truncated) if session else ""
    cached = session.batch.get("messages") if session else None
    if cached and cached["key"] == key:
        messages = BilingualMessages(**cached["result"])
    else:
        with console.status(f"[bold]{status_text}[/bold]"):
            messages = suggest_bilingual_messages(allow_truncated=allow_truncated)
        if session:
            session.verify()
            if messages.parsed_ok:
                session.batch["messages"] = {"key": key, "result": asdict(messages)}
                session.save()

    options: list[tuple[str, str]] = []
    en = messages.message_en or hint_en
    cn_msg = messages.message_cn or hint_cn
    if en:
        options.append(("en", en))
    if cn_msg:
        options.append(("cn", cn_msg))

    prefer = _normalize_msg_lang(prefer_lang or "") if prefer_lang else None
    if yes:
        # Automation cannot fall back to a manual menu or a different language.
        selected = {"en": messages.message_en, "cn": messages.message_cn}.get(prefer, "").strip()
        if not messages.parsed_ok or not selected:
            if session:
                session.batch.pop("messages", None)
                session.save()
            raise LLMError(
                "自动确认需要所选语言的有效提交信息；请重试。 / "
                "Auto-confirm requires a valid message in the selected language; retry the flow.",
                kind="bad_response",
            )
        return _commit_fixed_message(selected, chinese=chinese, flush=flush,
                                     expected_snapshot=expected_snapshot, confirm=False)
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

    _flow_commit(commit_message, expected_snapshot)
    console.print(
        ("[green]已提交：[/green] " if chinese else "[green]Committed:[/green] ")
        + commit_message
    )
    flush("commit")
    return True


def _flow_commit(message: str, snapshot: StagedSnapshot) -> None:
    session = current_session()
    if session:
        session.batch["selected_message"] = message
        session.save()
        session.commit(message, snapshot,
                       lambda: git_commit(message, expected_snapshot=snapshot))
    else:
        git_commit(message, expected_snapshot=snapshot)


def _stage_devflow(session, *, chinese: bool, flush) -> None:
    # ----- 1) ADD (AI suggest) -----
    console.print("暂存 / Stage", markup=False)
    if not is_worktree_dirty():
        session.update(phase="done")
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
        key = session.cache_key("stage", chinese=chinese)
        cached = session.data.get("stage_suggestion")
        if cached and cached["key"] == key:
            suggestion = StageSuggestion(**cached["result"])
        else:
            with console.status(f"[bold]{status_text}[/bold]"):
                suggestion = suggest_stage_paths(chinese=chinese)
            session.verify()
            if suggestion.parsed_ok:
                session.update(stage_suggestion={"key": key, "result": asdict(suggestion)})

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

        from gai.common.git import filter_addable_paths
        targets = filter_addable_paths(targets)
        if not targets:
            raise RuntimeError("No stageable paths selected")
        session.index_write("add", targets, lambda: git_add(targets),
                            updates={"phase": "running", "batch_status": "staged"})
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

    session.batch["status"] = "staged"
    session.update(phase="running")


def _run_splitflow(*, chinese: bool, remote: str | None, trace: bool = False,
                   plan: CommitBatchPlan | None = None, resume: bool = False, yes: bool = False) -> None:
    from gai.flow.runner import run_splitflow
    run_splitflow(chinese=chinese, remote=remote, trace=trace, plan=plan, resume=resume, yes=yes)


def _run_devflow(*, chinese: bool, remote: str | None, trace: bool = False,
                 suggest_split: bool = False, resume: bool = False) -> None:
    from gai.flow.runner import run_devflow
    run_devflow(chinese=chinese, remote=remote, trace=trace,
                suggest_split=suggest_split, resume=resume)
