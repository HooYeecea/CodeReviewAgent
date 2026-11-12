"""Cooperating JSONL readers/writers use a stable sidecar lock on both OSes."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time

_guard = threading.Lock()
_threads = {}
_local = threading.local()


@contextmanager
def log_lock(path: Path, *, timeout: float = 10):
    path = path.resolve()
    key = os.path.normcase(str(path))
    with _guard:
        mutex = _threads.setdefault(key, threading.RLock())
    if not mutex.acquire(timeout=timeout):
        raise TimeoutError(f"Log lock busy: {path}")
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = set()
    try:
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never unlink the lock: replacement of the data file must not change
        # the object used by another process to synchronize with this writer.
        with path.with_name(path.name + ".lock").open("a+b") as stream:
            # Windows permits locking beyond EOF. Do not initialize a byte
            # before locking: concurrent initializers can hit a locked region.
            deadline = time.monotonic() + timeout
            while True:
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Log lock busy: {path}") from exc
                    time.sleep(0.02)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        mutex.release()


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with log_lock(path):
        with path.open("r", encoding="utf-8") as stream:
            return stream.readlines()


def replace_lines(path: Path, lines) -> None:
    """Atomically replace data; callers doing read/modify/write hold log_lock."""
    with log_lock(path):
        fd, name = tempfile.mkstemp(prefix=path.name + "-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.writelines(lines)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


def append_row(path: Path, row: dict) -> None:
    encoded = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with log_lock(path):
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    # Isolate an incomplete tail from a previously killed writer.
                    stream.write(b"\n")
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())


def rotate(path: Path, *, max_bytes: int, keep_lines: int) -> None:
    with log_lock(path):
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return
        lines = read_lines(path)
        if len(lines) > keep_lines:
            replace_lines(path, lines[-keep_lines:])
