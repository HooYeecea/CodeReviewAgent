"""Durable, worktree-local flow state and reconciliation of interrupted Git writes."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path

from gai.common.git import GitError, ensure_repo, run_git, staged_snapshot

_CURRENT: ContextVar[FlowSession | None] = ContextVar("gai_flow_session", default=None)
TERMINAL = {"done", "aborted"}


def _valid_snapshot(value) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("worktree"), str)
            and isinstance(value.get("snapshot"), dict)
            and all(isinstance(value["snapshot"].get(k), str) for k in ("head", "tree", "ref")))


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


def read_state(directory: Path | None = None) -> dict | None:
    path = (directory or session_dir()) / "current.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != 1
                or data.get("kind") not in {"devflow", "splitflow"}
                or data.get("phase") not in {"prepare", "plan", "running", "push", *TERMINAL}
                or not isinstance(data.get("root"), str)
                or not Path(data["root"]).is_absolute()
                or not isinstance(data.get("batches"), list)
                or not _valid_snapshot(data.get("observed"))
                or not isinstance(data.get("id"), str)
                or len(data["id"]) != 32 or any(c not in "0123456789abcdef" for c in data["id"])
                or not isinstance(data.get("cursor"), int)
                or not 0 <= data["cursor"] <= len(data["batches"])):
            raise ValueError("Invalid checkpoint schema")
        for batch in data["batches"]:
            if (not isinstance(batch, dict) or not isinstance(batch.get("batch"), dict)
                    or not isinstance(batch.get("label"), str)
                    or batch.get("status") not in {"pending", "staged", "splitting", "committed", "skipped"}
                    or not isinstance(batch["batch"].get("title"), str)
                    or not isinstance(batch["batch"].get("paths"), list)):
                raise ValueError("Invalid checkpoint batch")
        pending = data.get("pending")
        if pending is not None and (
            not isinstance(pending, dict) or pending.get("operation") not in {"add", "unadd", "commit"}
            or not _valid_snapshot(pending.get("before")) or not isinstance(pending.get("tree"), str)
            or not isinstance(pending.get("updates"), dict)
        ):
            raise ValueError("Invalid pending operation")
        return data
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"无法读取流程检查点 / Cannot read flow checkpoint: {path}") from exc


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


def observed(root: Path) -> dict:
    return {"snapshot": asdict(staged_snapshot(root)), "worktree": worktree_digest(root)}


def mismatch() -> RuntimeError:
    return RuntimeError(
        "仓库、分支、暂存区或文件已变化，已停止恢复；保留所有改动。"
        "请检查后运行 gai flow abort，再重新规划。 / "
        "Repository state changed; inspect it, then use gai flow abort and start a new flow."
    )


class FlowSession:
    def __init__(self, directory: Path, data: dict):
        self.directory = directory
        self.data = data
        self.root = Path(data["root"])

    def save(self):
        atomic_json(self.directory / "current.json", self.data)

    def update(self, **values):
        self.data.update(values)
        self.save()

    @property
    def batch(self) -> dict:
        return self.data["batches"][self.data["cursor"]]

    def verify(self):
        if ensure_repo().resolve() != self.root or observed(self.root) != self.data["observed"]:
            raise mismatch()

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
        self.verify()
        before = self.data["observed"]
        fd, filename = tempfile.mkstemp(prefix="index-", dir=self.directory)
        os.close(fd)
        Path(filename).unlink()
        env = dict(os.environ, GIT_INDEX_FILE=filename)
        def temporary_git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
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
        self.update(pending={"operation": operation, "before": before,
                             "tree": tree, "updates": updates})
        self.verify()
        callback()
        self.reconcile()

    def commit(self, message: str, snapshot, callback):
        self.verify()
        self.update(pending={"operation": "commit", "before": self.data["observed"],
                             "tree": snapshot.tree, "message": message,
                             "updates": {"batch_status": "committed"}})
        callback()
        self.reconcile()

    def reconcile(self):
        pending = self.data.get("pending")
        if not pending:
            self.verify()
            return
        actual = observed(self.root)
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
        self.data.update(updates)
        self.update(observed=actual, pending=None)


@contextmanager
def session_scope(kind: str, *, resume: bool, chinese: bool, remote: str | None):
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
        from gai.common.git import clear_diff_cache
        clear_diff_cache()
        data = read_state(directory)
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
        if resume:
            if ensure_repo().resolve() != session.root:
                raise mismatch()
            session.reconcile()
        session.save()
        token = _CURRENT.set(session)
        previous_cwd = Path.cwd()
        try:
            os.chdir(session.root)
            yield session
        finally:
            os.chdir(previous_cwd)
            _CURRENT.reset(token)
            if session.data["phase"] not in TERMINAL:
                from gai.cli_common import console
                console.print(
                    f"流程进度已保存 / Progress saved: gai {session.data['kind']} --resume\n"
                    "查看 / Inspect: gai flow status; 放弃 / Discard: gai flow abort",
                    markup=False,
                )
