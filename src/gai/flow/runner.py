"""Checkpointed orchestration; UI and model helpers stay in flow.lib."""
from __future__ import annotations

from dataclasses import asdict

import typer

from gai.flow import lib
from gai.flow.devflow import CommitBatch, CommitBatchPlan
from gai.flow.session import session_scope
from gai.common.git import filter_addable_paths


def record(batch: CommitBatch, label: str, *, lang: str = "", depth: int = 1,
           parent: str | None = None) -> dict:
    return {"batch": asdict(batch), "label": label, "lang": lang, "depth": depth,
            "parent": parent, "status": "pending"}


def pause():
    raise typer.Exit(code=0)


def auto_confirm(session) -> bool:
    return session.data["kind"] == "splitflow" and session.data.get("auto_confirm") is True


def flush_for(chinese, trace):
    return lambda label: lib._print_step_trace(trace=trace, chinese=chinese, step=label)


def stage(session, paths, *, updates):
    paths = filter_addable_paths(paths)
    if not paths:
        raise RuntimeError("批次没有可暂存路径 / No stageable paths in batch")
    session.index_write("add", paths, lambda: lib.git_add(paths), updates=updates)


def unstage(session, *, updates):
    if lib.has_staged_changes():
        session.index_write("unadd", ["."], lambda: lib.git_unadd(["."]), updates=updates)
    else:
        values = dict(updates)
        if "batch_status" in values:
            session.batch["status"] = values.pop("batch_status")
        session.update(**values)


def finish_push(session, *, chinese, flush):
    session.verify(strict=True)
    session.update(phase="push", step="push")
    if session.data.get("no_push"):
        session.update(phase="done", completion="local_only")
        lib.console.print("本地流程已完成，未推送 / Local flow completed without pushing", markup=False)
        return
    # Never replay a push blindly. The normal push helper fetches and checks the
    # remote on every attempt, including an interrupted successful push.
    if not auto_confirm(session) and not lib.Confirm.ask(
        "确认检查并推送？" if chinese else "Check and push to remote?", default=True,
    ):
        pause()
    session.verify(strict=True)
    lib._do_flow_push(session, chinese=chinese, yes=auto_confirm(session))
    session.verify(strict=True)
    session.update(phase="done", completion="pushed", last_success="push")
    flush("push")


def split_current(session, *, chinese, flush):
    item = session.batch
    batch = CommitBatch(**item["batch"])
    if item["status"] != "splitting":
        unstage(session, updates={"batch_status": "splitting"})
    if not item.get("children_plan"):
        with lib.console.status("正在拆分二级批次..." if chinese else "Planning level-2 batches..."):
            plan = lib.suggest_commit_batches(chinese=chinese, paths=batch.paths,
                                             message_lang=item["lang"], require_concrete_messages=True)
        session.verify()
        children = lib.sanitize_commit_batches(plan.batches)
        # A child cannot escape the approved parent batch or repeat another child.
        from gai.flow.devflow import normalize_commit_batches
        children = normalize_commit_batches(children, allowed_paths=batch.paths, chinese=chinese)
        item["children_plan"] = {"batches": [asdict(b) for b in children], "summary": plan.summary}
        session.save()
    plan = item["children_plan"]
    children = [CommitBatch(**b) for b in plan["batches"]]
    if len(children) < 2:
        item["split_attempted"] = True
        session.save()
        stage(session, batch.paths, updates={"batch_status": "staged"})
        return
    lib._print_level2_plan(children, parent_idx=item["label"], parent_title=batch.title,
                          summary=plan["summary"], chinese=chinese, message_lang=item["lang"])
    if not auto_confirm(session) and not lib.Confirm.ask(
        "确认二级批次？" if chinese else "Confirm level-2 batches?", default=True,
    ):
        pause()
    session.verify()
    position = session.data["cursor"]
    session.data.setdefault("parents", {})[item["label"]] = item
    session.data["batches"][position:position + 1] = [
        record(b, f"{item['label']}.{i}", lang=item["lang"], depth=2, parent=item["label"])
        for i, b in enumerate(children, 1)
    ]
    session.save()
    flush("split")


def execute_batches(session, *, chinese, flush, trace, suggest_split=False):
    automatic = auto_confirm(session)
    while session.data["cursor"] < len(session.data["batches"]):
        session.verify()
        item = session.batch
        if item["status"] in {"committed", "skipped"}:
            session.update(cursor=session.data["cursor"] + 1)
            continue
        batch = CommitBatch(**item["batch"])
        lib.console.print(f"批次 / Batch {item['label']}: {batch.title}", markup=False)
        if item["status"] == "restaging":
            if lib.has_staged_changes():
                paths = batch.paths
                session.index_write("unadd", paths, lambda: lib.git_unadd(paths),
                                    updates={"batch_status": "pending"})
            else:
                item["status"] = "pending"
                session.save()
        if item["status"] == "pending":
            if lib.has_staged_changes():
                # Initial index clearing and previous batch completion are explicit.
                raise RuntimeError("暂存区不为空，拒绝覆盖 / Refusing to overwrite staged changes")
            stage(session, batch.paths, updates={"batch_status": "staged"})
        if item["status"] == "splitting":
            split_current(session, chinese=chinese, flush=flush)
            continue
        if not lib.has_staged_changes():
            item["status"] = "skipped"
            session.save()
            continue
        if session.data["kind"] == "splitflow" and item["depth"] == 1 and not item.get("split_attempted"):
            _, _, exceeds = lib.staged_diff_size()
            if exceeds and len(batch.paths) >= 2:
                split_current(session, chinese=chinese, flush=flush)
                continue
        snapshot = lib._run_staged_review(
            chinese=chinese, review_cn=session.data["review_cn"], flush=flush,
            allow_truncated=session.data["kind"] == "splitflow",
            offer_splitflow=session.data["kind"] == "devflow", suggest_split=suggest_split,
            remote=session.data.get("remote"), trace=trace, auto_continue=automatic or item["depth"] == 2,
        )
        if snapshot is None:
            pause()
        if item.get("selected_message"):
            ok = lib._commit_fixed_message(item["selected_message"], chinese=chinese, flush=flush,
                                          expected_snapshot=snapshot, confirm=not automatic)
        elif item["depth"] == 2 and batch.commit_message:
            ok = lib._commit_fixed_message(batch.commit_message, chinese=chinese, flush=flush,
                                          expected_snapshot=snapshot, confirm=False)
        else:
            ok = lib._pick_and_commit_message(
                chinese=chinese, flush=flush, expected_snapshot=snapshot,
                hint_en=batch.message_hint_en, hint_cn=batch.message_hint_cn,
                allow_truncated=session.data["kind"] == "splitflow", prefer_lang=item["lang"] or None,
                yes=automatic,
            )
        if not ok:
            pause()
        if item["status"] != "committed":
            raise RuntimeError("Commit completed without a durable checkpoint")
    if not any(b["status"] == "committed" for b in session.data["batches"]) and not session.data.get("completed_batches"):
        raise RuntimeError("没有产生提交 / No commits created")
    session.update(phase="push")


def run_splitflow(*, chinese, remote, trace=False, plan: CommitBatchPlan | None = None,
                  resume=False, yes=False, interactive=False, no_push=False,
                  review_current=False, replan=False):
    if yes and interactive:
        raise RuntimeError("--yes 与 --interactive 不能同时使用 / Choose --yes or --interactive")
    if review_current and replan:
        raise RuntimeError("--review-current 与 --replan 不能同时使用 / Choose one recovery mode")
    if (review_current or replan) and not resume:
        raise RuntimeError("重新审查或规划需要 --resume / Recovery mode requires --resume")
    recovery = "current" if review_current else "replan" if replan else None
    with session_scope("splitflow", resume=resume, chinese=chinese, remote=remote,
                       recovery=recovery, yes=yes, interactive=interactive) as session:
        chinese = session.data["chinese"]
        if session.data["phase"] == "done":
            return
        # Omission on resume preserves the saved mode; explicit --yes can enable it.
        if interactive:
            session.update(auto_confirm=False)
        elif yes or "auto_confirm" not in session.data:
            session.update(auto_confirm=bool(yes))
        if no_push or "no_push" not in session.data:
            session.update(no_push=bool(no_push))
        automatic = auto_confirm(session)
        if automatic:
            lib.console.print(
                ("自动确认已开启（仅本地提交）。" if session.data["no_push"] else
                 "自动确认已开启：仅选择提交词语言，随后自动执行至推送。") if chinese else
                ("Auto-confirm enabled (local commits only)." if session.data["no_push"] else
                 "Auto-confirm enabled: choose commit message language, then continue through push."),
                markup=False,
            )
        flush = flush_for(chinese, trace)
        if session.data["phase"] == "prepare":
            if not lib.is_worktree_dirty():
                session.update(phase="done")
                raise RuntimeError("工作区干净 / Working tree is clean")
            if lib.has_staged_changes() and not automatic and not lib.Confirm.ask(
                "分批流程需要清空暂存区，继续？" if chinese else "Unstage changes for splitflow?", default=True,
            ):
                pause()
            unstage(session, updates={"phase": "plan"})
        if session.data["phase"] == "plan":
            if session.data["plan"] is None:
                session.update(step="plan")
                if plan is None:
                    with lib.console.status("正在规划..." if chinese else "Planning..."):
                        plan = lib.suggest_commit_batches(chinese=chinese)
                session.verify()
                batches = lib.sanitize_commit_batches(plan.batches)
                if not batches:
                    lib.err_console.print("分批计划为空 / Empty batch plan")
                    raise typer.Exit(1)
                session.update(plan={"batches": [asdict(b) for b in batches], "summary": plan.summary}, last_success="plan")
            saved = session.data["plan"]
            batches = [CommitBatch(**b) for b in saved["batches"]]
            lib._print_batch_plan(batches, summary=saved["summary"], chinese=chinese)
            if not session.data.get("plan_confirmed"):
                if not automatic and not lib.Confirm.ask(
                    "按以上批次继续？" if chinese else "Proceed with this plan?", default=True,
                ):
                    pause()
                session.update(plan_confirmed=True)
            if session.data["languages"] is None:
                session.update(languages=lib._ask_splitflow_message_langs(batches, chinese=chinese))
            if "review_cn" not in session.data:
                session.update(review_cn=chinese if automatic else lib._review_language(chinese=chinese))
            session.verify()
            session.update(phase="running", batches=[
                record(b, str(i + len(session.data.get("completed_batches", []))), lang=lang)
                for i, (b, lang) in enumerate(zip(batches, session.data["languages"]), 1)
            ])
        if session.data["phase"] == "running":
            execute_batches(session, chinese=chinese, flush=flush, trace=trace)
        finish_push(session, chinese=chinese, flush=flush)


def run_devflow(*, chinese, remote, trace=False, suggest_split=False, resume=False):
    with session_scope("devflow", resume=resume, chinese=chinese, remote=remote) as session:
        chinese = session.data["chinese"]
        if "suggest_split" not in session.data:
            session.update(suggest_split=suggest_split)
        suggest_split = session.data["suggest_split"]
        flush = flush_for(chinese, trace)
        if session.data["phase"] == "prepare":
            if not session.data["batches"]:
                session.update(batches=[record(CommitBatch(title="devflow", paths=[], reason=""), "1")])
            lib._stage_devflow(session, chinese=chinese, flush=flush)
        if "review_cn" not in session.data:
            session.update(review_cn=lib._review_language(chinese=chinese))
        if session.data["phase"] == "running":
            execute_batches(session, chinese=chinese, flush=flush, trace=trace, suggest_split=suggest_split)
        finish_push(session, chinese=chinese, flush=flush)
