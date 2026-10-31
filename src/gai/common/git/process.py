"""Bounded subprocesses with process-tree cleanup for Git writes and transports.

On Windows the supervisor is assigned to a kill-on-close Job before it is
allowed to launch Git. On POSIX its pipe watchdog kills the session on parent
death. The supervisor is deliberately a standalone stdlib-only script.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

NETWORK = {"fetch", "push", "pull", "clone", "ls-remote"}
SUPERVISED = NETWORK | {"add", "restore", "commit", "reset", "checkout", "switch",
                        "merge", "rebase", "read-tree", "update-ref"}


def command_timeout(args) -> float:
    network = any(a in NETWORK for a in args[:3])
    key = "GAI_GIT_NETWORK_TIMEOUT" if network else "GAI_GIT_TIMEOUT"
    seconds = float(os.environ.get(key, "180" if network else "60"))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{key} must be a positive number of seconds")
    return seconds


class WindowsJob:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Limits(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                        ("flags", w.DWORD), ("min_ws", c.c_size_t), ("max_ws", c.c_size_t),
                        ("active", w.DWORD), ("affinity", c.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Extended(c.Structure):
            _fields_ = [("basic", Limits), ("io", c.c_uint64 * 6),
                        ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                        ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]
        self.api = c.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_managed(command, *, cwd=None, env=None, timeout=60):
    job = WindowsJob() if os.name == "nt" else None
    process = None
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--supervisor"],
                cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if job:
                job.assign(process)
            process.stdin.write((json.dumps(list(command)) + "\n").encode())
            process.stdin.flush()
            process.wait(timeout=timeout)
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(command, process.returncode,
                stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace"))
    finally:
        if job:
            job.close()
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()


def _supervise():
    line = sys.stdin.buffer.readline()
    if not line:
        return 1
    command = json.loads(line)
    if os.name != "nt":
        def watch_parent():
            while os.read(sys.stdin.fileno(), 1):
                pass
            os.killpg(os.getpgrp(), signal.SIGKILL)
        threading.Thread(target=watch_parent, daemon=True).start()
    try:
        return subprocess.call(command, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        print("git executable not found on PATH", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(_supervise())
