"""Cross-process append/merge/cleanup and interrupted atomic rewrites."""
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from gai.common.jsonl import append_row, log_lock, read_lines, replace_lines, rotate
from gai.history import store


def _worker(folder, mode, ready, start):
    from gai.history.commands import CommandRecord, append_command_record
    from gai.common.llm.history import UsageRecord, append_usage_record
    import gai.history.commands as command_history
    import gai.common.llm.history as usage_history
    import gai.history.report as command_report
    import gai.usage.report as usage_report
    command_report.sync_history_data_file = lambda **k: None
    usage_report.sync_usage_data_file = lambda **k: None
    for module in (command_history, usage_history):
        module._MAX_BYTES = 1
        module._KEEP_TAIL_LINES = 100
    folder = Path(folder)
    commands, usage = folder / "commands.jsonl", folder / "usage.jsonl"
    os.environ["GAI_HISTORY_LOG_GLOBAL"] = str(commands)
    os.environ["GAI_USAGE_LOG_GLOBAL"] = str(usage)
    ready.set()
    assert start.wait(20)
    if mode.startswith("writer"):
        for i in range(12):
            stamp = f"2026-11-03T12:00:{i:02d}.{mode[-1]}+08:00"
            append_command_record(CommandRecord(ts=stamp, command="review", argv=[mode, str(i)],
                                                 exit_code=0, ok=True, repo_name="project"), path=commands)
            append_usage_record(UsageRecord(ts=stamp, git_user="user", git_email="u@example.invalid",
                                           action="review", repo_name="project", model="real-model"), path=usage)
    else:
        for _ in range(8):
            store.merge_jsonl_into(commands, [(folder / "source-commands.jsonl", "project")])
            store.merge_jsonl_into(usage, [(folder / "source-usage.jsonl", "project")])
            # Force cleanup to rewrite while real records are being appended.
            for path in (commands, usage):
                append_row(path, {"ts": "discard", "repo_name": "test_ephemeral"})
            store.cleanup_global_logs()
            for path in (commands, usage):
                assert all(isinstance(json.loads(line), dict) for line in read_lines(path))


def test_public_writers_merge_and_cleanup_do_not_lose_rows(tmp_path):
    # The first append must rotate old disposable rows; cleanup also removes
    # these rows while preserving every real record from concurrent writers.
    seed = "".join(json.dumps({"ts": f"2000-{i:03d}", "repo_name": "test_old"}) + "\n"
                   for i in range(110))
    for name in ("commands.jsonl", "usage.jsonl"):
        (tmp_path / name).write_text(seed)
    (tmp_path / "source-commands.jsonl").write_text(json.dumps({
        "ts": "2026-11-01", "command": "review", "repo_name": "project"}) + "\n")
    (tmp_path / "source-usage.jsonl").write_text(json.dumps({
        "ts": "2026-11-01", "action": "review", "model": "real-model", "repo_name": "project"}) + "\n")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    ready = [context.Event() for _ in range(4)]
    processes = [context.Process(target=_worker, args=(str(tmp_path), mode, event, start))
                 for mode, event in zip(("writer1", "writer2", "maintainer1", "maintainer2"), ready)]
    try:
        for process in processes:
            process.start()
        assert all(event.wait(20) for event in ready)
        start.set()
        for process in processes:
            process.join(40)
            assert process.exitcode == 0
        for name in ("commands.jsonl", "usage.jsonl"):
            rows = [json.loads(line) for line in read_lines(tmp_path / name)]
            assert len(rows) == 25
            assert len({r["ts"] for r in rows}) == 25
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)


def test_failed_replace_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "data.jsonl"
    append_row(path, {"old": True})
    original = path.read_bytes()
    def fail(*a):
        raise OSError("disk error before replacement")
    monkeypatch.setattr("gai.common.jsonl.os.replace", fail)
    with pytest.raises(OSError):
        replace_lines(path, ['{"new":true}\n'])
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def _crash_rewrite(path):
    def lines():
        yield '{"partial":true}\n'
        os._exit(37)
    replace_lines(Path(path), lines())


def test_killed_writer_keeps_data_and_releases_lock(tmp_path):
    path = tmp_path / "data.jsonl"
    append_row(path, {"old": True})
    process = multiprocessing.get_context("spawn").Process(target=_crash_rewrite, args=(str(path),))
    process.start()
    try:
        process.join(20)
        assert process.exitcode == 37
        append_row(path, {"after": True})
        assert [json.loads(line) for line in read_lines(path)] == [{"old": True}, {"after": True}]
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_partial_append_does_not_swallow_next_valid_record(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_bytes(b'{"unfinished":')
    append_row(path, {"valid": True})
    assert json.loads(read_lines(path)[-1]) == {"valid": True}


def test_rotation_and_append_share_reentrant_lock(tmp_path):
    path = tmp_path / "data.jsonl"
    with log_lock(path):
        for i in range(5):
            append_row(path, {"id": i})
        rotate(path, max_bytes=1, keep_lines=2)
        append_row(path, {"id": 5})
    assert [json.loads(line)["id"] for line in read_lines(path)] == [3, 4, 5]


def test_merge_does_not_overwrite_unreadable_target(tmp_path, monkeypatch):
    path, source = tmp_path / "data.jsonl", tmp_path / "source.jsonl"
    append_row(path, {"ts": "old", "command": "review"})
    append_row(source, {"ts": "new", "command": "review"})
    original = path.read_bytes()
    read = store._read_jsonl_dicts
    def fail(target, **kwargs):
        if target == path:
            raise PermissionError("cannot read target")
        return read(target, **kwargs)
    monkeypatch.setattr(store, "_read_jsonl_dicts", fail)
    with pytest.raises(PermissionError):
        store.merge_jsonl_into(path, [(source, "project")])
    assert path.read_bytes() == original
