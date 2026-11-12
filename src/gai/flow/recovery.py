"""Explicit recovery after edits; never rewrite HEAD or working files."""
import copy

import typer
from rich.prompt import Confirm

from gai.cli_common import console
from gai.common.git import is_worktree_dirty, run_git
from gai.flow.fingerprint import changed_files
from gai.flow.session import observed, state_differences


def accept_changes(session, mode, *, yes=False):
    data = session.data
    actual = session.actual(strict=True)
    old = data["observed"]
    if any(actual["snapshot"][k] != old["snapshot"][k] for k in ("head", "ref")):
        raise RuntimeError("HEAD 或分支已变化，不能重用原流程；请先核实待完成操作。 / HEAD or branch changed")
    if session.from_backup:
        raise RuntimeError("请先恢复有效检查点，再重新规划 / Restore a valid checkpoint before replanning")
    # A pending command with unchanged HEAD cannot have created a commit.
    # The explicitly selected recovery will review the new index from scratch.
    if mode == "current":
        if data["phase"] != "running" or data["cursor"] >= len(data["batches"]):
            raise RuntimeError("没有可重新审查的当前批次 / No current batch to review")
        item = session.batch
        if item["status"] in ("committed", "skipped"):
            raise RuntimeError("当前批次已完成，请重规划剩余改动 / Current batch is finished; use --replan")
        if "files" not in old:
            raise RuntimeError("旧检查点缺少文件记录，请使用 --replan / Legacy checkpoint requires --replan")
        allowed = set(item["batch"]["paths"])
        outside = set(changed_files(old["files"], actual["files"])) - allowed
        staged = run_git("diff", "--cached", "--name-only", "-z", cwd=session.root)
        if staged.returncode:
            raise RuntimeError(staged.stderr)
        outside |= set(staged.stdout.split("\0")) - {""} - allowed
        if outside:
            raise RuntimeError("当前批次之外也有变化，请使用 --replan / Changes outside current batch: "
                               + ", ".join(sorted(outside)))
    changes = state_differences(old, actual)
    console.print("\n".join(changes) or "Git 状态未变化 / Git state unchanged", markup=False)
    if not yes and not Confirm.ask(
        "接受这些改动并重新审查当前批次？" if mode == "current" else
        "保留已完成提交，重新规划全部剩余改动？", default=False,
    ):
        raise typer.Exit(0)
    # Confirmation may take minutes. Do not accept a second, unseen change.
    if session.actual(strict=True) != actual:
        raise RuntimeError("确认期间文件又发生变化，请重试 / Files changed during confirmation")
    data.setdefault("recovery_history", []).append({
        "mode": mode, "revision": data.get("revision", 0),
        "plan": copy.deepcopy(data["plan"]), "batches": copy.deepcopy(data["batches"]),
    })
    data["observed"] = observed(session.root)
    data["pending"] = None
    data.pop("last_error", None)
    if mode == "current":
        for key in ("review", "messages", "selected_message", "children_plan", "split_attempted"):
            session.batch.pop(key, None)
        for key in ("commit_message", "message_hint_en", "message_hint_cn"):
            session.batch["batch"][key] = ""
        session.batch["status"] = "restaging"
    else:
        data.setdefault("completed_batches", []).extend(
            copy.deepcopy(b) for b in data["batches"] if b["status"] == "committed")
        data.update(batches=[], cursor=0, plan=None, languages=None, plan_confirmed=False,
                    phase="prepare" if is_worktree_dirty() else "push")
        data.pop("push_target", None)
        data.pop("verified_push_targets", None)
        if data["phase"] == "push" and not data["completed_batches"]:
            data.update(phase="done", completion="local_only")
    session.save()
