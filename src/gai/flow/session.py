"""Durable, worktree-local flow state and reconciliation of interrupted Git writes."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path

from gai.common.git import GitError, ensure_repo, run_git, staged_snapshot

_CURRENT: ContextVar[FlowSession | None] = ContextVar("gai_flow_session", default=None)
TERMINAL = {"done", "aborted"}


def current_session():
    return _CURRENT.get()


def git_text(*args: str, cwd: Path | None = None) -> str:
    result = run_git(*args, cwd=cwd)
    if result.returncode:
        raise GitError(result.stderr.strip() or "Git state lookup failed")
    return result.stdout.strip()


def session_dir() -> Path:
    ensure_repo()
    return Path(git_text("rev-parse", "--absolute-git-dir")) / "gai" / "flows"


def read_state(directory: Path | None = None, *, allow_backup=False) -> dict | None:
    from gai.flow.checkpoint import load
    directory = directory or session_dir()
    path = directory / "current.json"
    if not path.exists() and not (directory / "previous.json").exists():
        return None
    try:
        return load(path)
    except RuntimeError:
        if not allow_backup:
            raise
        data = load(directory / "previous.json")
        data.pop("checksum", None)
        data["recovered_backup"] = True
        data["_backup_pending"] = True
        return data


def write_checkpoint(directory, data):
    from datetime import datetime, timezone
    from gai.flow.checkpoint import load, checksum
    path = directory / "current.json"
    if path.exists():
        try:
            previous = load(path)
        except RuntimeError:
            # Preserve corrupt bytes for diagnosis; never use them as the backup.
            path.replace(directory / f"corrupt-{uuid.uuid4().hex}.json")
        else:
            atomic_json(directory / "previous.json", previous)
    updated = dict(data)
    updated.pop("checksum", None)
    updated["revision"] = data.get("revision", 0) + 1
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated.setdefault("created_at", updated["updated_at"])
    updated["checksum"] = checksum(updated)
    atomic_json(path, updated)
    if updated["phase"] in TERMINAL:
        # A backup must not revive an intentionally finished/discarded session.
        atomic_json(directory / "previous.json", updated)
    data.clear()
    data.update(updated)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix="checkpoint-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def flow_lock(directory: Path):
    """OS-owned lock: a killed process releases it without stale PID cleanup."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "session.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有流程正在运行 / Another flow is running in this worktree") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def worktree_digest(root: Path) -> str:
    result = run_git("ls-files", "--cached", "--others", "--exclude-standard", "-z", cwd=root)
    if result.returncode:
        raise GitError(result.stderr)
    digest = hashlib.sha256()
    for name in sorted(set(result.stdout.split("\0")) - {""}):
        # Runtime reports/logs are written by every command and do not affect a plan.
        if name == ".gai" or name.startswith(".gai/"):
            continue
        path = root / name
        try:
            mode = path.lstat().st_mode
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(str(mode).encode() + b"\0")
            if stat.S_ISLNK(mode):
                digest.update(os.readlink(path).encode("utf-8"))
            elif path.is_file():
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
            elif path.is_dir():
                # Include dirty submodule contents, not just their status letters.
                if ensure_repo(path).resolve() == path.resolve():
                    digest.update(git_text("rev-parse", "HEAD", cwd=path).encode())
                    digest.update(worktree_digest(path).encode())
                else:
                    digest.update(b"uninitialized-submodule")
        except FileNotFoundError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()


def observed(root: Path, *, cache=None, strict=True, legacy=False) -> dict:
    if legacy:
        return {"snapshot": asdict(staged_snapshot(root)), "worktree": worktree_digest(root)}
    from gai.flow.fingerprint import file_manifest, manifest_digest
    files = file_manifest(root, cache=cache, strict=strict)
    return {"snapshot": asdict(staged_snapshot(root)), "worktree": manifest_digest(files), "files": files}


def state_differences(expected, actual):
    from gai.flow.fingerprint import changed_files
    changes = []
    labels = {"ref": "分支 / branch", "head": "HEAD", "tree": "暂存区 / index"}
    for key, label in labels.items():
        if expected["snapshot"][key] != actual["snapshot"][key]:
            changes.append(f"{label}: {expected['snapshot'][key]} → {actual['snapshot'][key]}")
    if expected["worktree"] != actual["worktree"]:
        if "files" in expected and "files" in actual:
            names = changed_files(expected["files"], actual["files"])
            changes.append("文件 / files: " + ", ".join(names[:12]) + (" …" if len(names) > 12 else ""))
        else:
            changes.append("文件内容变化（旧检查点无逐文件记录） / Working files changed")
    return changes


def mismatch() -> RuntimeError:
    return RuntimeError(
        "仓库、分支、暂存区或文件已变化，已停止恢复；保留所有改动。"
        "请检查后运行 gai flow abort，再重新规划。 / "
        "Repository state changed; inspect it, then use gai flow abort and start a new flow."
    )


def check_git_idle():
    ref = run_git("symbolic-ref", "-q", "HEAD").stdout.strip()
    paths = ["index.lock", "HEAD.lock", "packed-refs.lock", "MERGE_HEAD", "rebase-merge", "rebase-apply"]
    if ref:
        paths.append(ref + ".lock")
    busy = [name for name in paths if Path(git_text("rev-parse", "--git-path", name)).exists()]
    if busy:
        raise GitError("Git 操作尚未结束或留有锁；不会自动删除。 / Git operation or lock present: "
                       + ", ".join(busy), code="git_busy")


def preview_recovery():
    """Use a detached state copy to reconcile intent without writing a checkpoint."""
    import copy
    from gai.cli_common import console
    directory = session_dir()
    with flow_lock(directory):
        check_git_idle()
        data = read_state(directory, allow_backup=True)
        if not data:
            return
        candidate = FlowSession(directory, copy.deepcopy(data))
        if ensure_repo().resolve() != candidate.root:
            raise mismatch()
        candidate.save = lambda: None
        candidate.reconcile()
        console.print("恢复预检通过；未执行暂存、提交或推送。 / Recovery preflight passed.", markup=False)


class FlowSession:
    def __init__(self, directory: Path, data: dict):
        self.directory = directory
        self.data = data
        self.root = Path(data["root"])
        self.from_backup = data.pop("_backup_pending", False)
        self.saved_ok = False
        self.save_failed = False
        self.file_cache = {}

    def save(self):
        self.saved_ok = False
        try:
            write_checkpoint(self.directory, self.data)
        except BaseException:
            self.save_failed = True
            raise
        self.saved_ok = True
        self.save_failed = False

    def update(self, **values):
        self.data.update(values)
        self.save()

    @property
    def batch(self) -> dict:
        return self.data["batches"][self.data["cursor"]]

    def actual(self, *, strict=True):
        return observed(self.root, cache=self.file_cache, strict=strict,
                        legacy=not self.data["observed"]["worktree"].startswith("v2:"))

    def differences(self):
        if ensure_repo().resolve() != self.root:
            return ["仓库位置变化 / Repository location changed"]
        return state_differences(self.data["observed"], self.actual())

    def verify(self, *, strict=False):
        if ensure_repo().resolve() != self.root:
            raise mismatch()
        actual = self.actual(strict=strict)
        changes = state_differences(self.data["observed"], actual)
        if changes:
            raise RuntimeError(str(mismatch()) + "\n" + "\n".join(changes))

    def record_failure(self, exc):
        # Annotate the last durable state, never flush a failed in-memory update.
        if self.save_failed or (self.from_backup and not self.saved_ok):
            return
        from datetime import datetime, timezone
        try:
            durable = read_state(self.directory)
            if not durable or durable["phase"] in TERMINAL:
                return
            kind = getattr(exc, "kind", None) or getattr(exc, "code", None) or type(exc).__name__
            durable["last_error"] = {"kind": kind, "phase": durable["phase"],
                "step": durable.get("step", durable["phase"]),
                "batch": durable["cursor"], "at": datetime.now(timezone.utc).isoformat()}
            write_checkpoint(self.directory, durable)
        except (OSError, RuntimeError):
            pass  # Preserve the original failure.

    def cache_key(self, purpose: str, **options) -> str:
        from gai.common.config import load_settings
        from gai.common.llm import prompts
        settings = load_settings()
        # Hash configuration, never persist credentials or the endpoint URL.
        value = [purpose, settings.model, settings.base_url, settings.max_diff_chars,
                 settings.ignore_patterns, options, Path(prompts.__file__).read_text(encoding="utf-8")]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def index_write(self, operation: str, paths: list[str], callback, *, updates: dict):
        """Predict the index tree in a disposable index before touching the real one."""
        self.verify(strict=True)
        before = self.data["observed"]
        fd, filename = tempfile.mkstemp(prefix="index-", dir=self.directory)
        os.close(fd)
        Path(filename).unlink()
        env = dict(os.environ, GIT_INDEX_FILE=filename)
        def temporary_git(*args):
            result = run_git(*args, cwd=self.root, env=env)
            if result.returncode:
                raise GitError(result.stderr.strip())
            return result.stdout.strip()
        try:
            temporary_git("read-tree", before["snapshot"]["tree"])
            if operation == "add":
                temporary_git("add", "--", *paths)
            else:
                temporary_git("restore", "--staged", "--", *paths)
            tree = temporary_git("write-tree")
        finally:
            Path(filename).unlink(missing_ok=True)
            Path(filename + ".lock").unlink(missing_ok=True)
        self.data["step"] = "stage" if operation == "add" else "unstage"
        self.update(pending={"operation": operation, "before": before,
                             "tree": tree, "updates": updates})
        self.verify()
        callback()
        self.reconcile()

    def commit(self, message: str, snapshot, callback):
        self.verify(strict=True)
        self.data["step"] = "commit"
        self.update(pending={"operation": "commit", "before": self.data["observed"],
                             "tree": snapshot.tree, "message": message,
                             "updates": {"batch_status": "committed"}})
        callback()
        self.reconcile()

    def reconcile(self):
        pending = self.data.get("pending")
        if not pending:
            self.verify(strict=True)
            return
        actual = self.actual(strict=True)
        before = pending["before"]
        operation = pending["operation"]
        if actual == before:
            if operation != "commit" and pending["tree"] == before["snapshot"]["tree"]:
                updates = dict(pending["updates"])
                if "batch_status" in updates:
                    self.batch["status"] = updates.pop("batch_status")
                self.data.update(updates)
            # The command did not take effect. Retrying must still pass normal prompts.
            self.update(pending=None)
            return
        snap, old = actual["snapshot"], before["snapshot"]
        match = (actual["worktree"] == before["worktree"]
                 and snap["ref"] == old["ref"] and snap["tree"] == pending["tree"])
        if operation == "commit":
            details = git_text("show", "-s", "--format=%P%x00%T%x00%B", "HEAD", cwd=self.root).split("\0", 2)
            match = (match and snap["head"] != old["head"] and len(details) == 3
                     and details[0] == old["head"] and details[1] == pending["tree"]
                     and details[2].strip() == pending["message"].strip())
        else:
            match = match and snap["head"] == old["head"]
        if not match:
            raise mismatch()
        updates = dict(pending["updates"])
        if "batch_status" in updates:
            self.batch["status"] = updates.pop("batch_status")
        if operation == "commit":
            self.batch["commit"] = snap["head"]
        self.data["last_success"] = operation
        self.data.update(updates)
        self.update(observed=actual, pending=None)


@contextmanager
def session_scope(kind: str, *, resume: bool, chinese: bool, remote: str | None,
                  recovery=None, yes=False, interactive=False):
    nested = current_session()
    if nested is not None:
        if kind != "splitflow" or nested.data["kind"] != "devflow":
            raise RuntimeError("A flow is already active")
        nested.verify()
        nested.update(kind="splitflow", phase="prepare", batches=[], cursor=0,
                      plan=None, languages=None, plan_confirmed=False)
        yield nested
        return
    directory = session_dir()
    with flow_lock(directory):
        check_git_idle()
        from gai.common.git import clear_diff_cache
        clear_diff_cache()
        data = read_state(directory, allow_backup=resume)
        if resume:
            if not data or data["phase"] in TERMINAL:
                raise RuntimeError("没有可恢复的流程 / No unfinished flow to resume")
            if data["kind"] != kind:
                raise RuntimeError(f"请运行 / Run: gai {data['kind']} --resume")
            if remote is not None and remote != data.get("remote"):
                raise RuntimeError("恢复时不能更换远程，请先 gai flow abort / Remote differs from saved flow")
        else:
            if data and data["phase"] not in TERMINAL:
                raise RuntimeError(f"存在未完成流程；运行 gai {data['kind']} --resume 或 gai flow abort")
            if data:
                atomic_json(directory / f"{data['id']}.json", data)
            root = ensure_repo().resolve()
            data = {"schema": 1, "id": uuid.uuid4().hex, "kind": kind, "root": str(root),
                    "phase": "prepare", "chinese": chinese, "remote": remote,
                    "batches": [], "cursor": 0, "plan": None, "languages": None,
                    "observed": observed(root), "pending": None}
            data["initial_snapshot"] = data["observed"]["snapshot"]
        session = FlowSession(directory, data)
        token = None
        previous_cwd = Path.cwd()
        try:
            if resume:
                if ensure_repo().resolve() != session.root:
                    raise mismatch()
                if recovery:
                    from gai.flow.recovery import accept_changes
                    accept_changes(session, recovery, yes=yes or (data.get("auto_confirm", False) and not interactive))
                else:
                    session.reconcile()
                if not session.data["observed"]["worktree"].startswith("v2:"):
                    session.data["observed"] = observed(session.root)
            session.save()
            token = _CURRENT.set(session)
            os.chdir(session.root)
            yield session
        except BaseException as exc:
            if getattr(exc, "exit_code", None) != 0:
                session.record_failure(exc)
            raise
        finally:
            os.chdir(previous_cwd)
            if token is not None:
                _CURRENT.reset(token)
            if token is not None and session.data["phase"] not in TERMINAL:
                from gai.cli_common import console
                console.print(
                    (f"流程进度已保存 / Progress saved: gai {session.data['kind']} --resume\n"
                     if session.saved_ok else "最新进度保存失败；请先查看检查点 / Checkpoint save failed; inspect saved state.\n") +
                    "查看 / Inspect: gai flow status --check; 放弃 / Discard: gai flow abort",
                    markup=False,
                )
