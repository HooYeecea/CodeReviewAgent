"""Tests for git command tracing."""

from gai.git_ops import get_traced_commands, run_git, set_tracing


def test_trace_records_commands():
    set_tracing(True)
    # May fail if not in a repo, but still should record
    run_git("rev-parse", "--is-inside-work-tree")
    cmds = get_traced_commands()
    assert any(c.startswith("git rev-parse") for c in cmds)
    set_tracing(False)
    assert get_traced_commands() == []


def test_trace_disabled_records_nothing():
    set_tracing(False)
    run_git("--version")
    assert get_traced_commands() == []
