"""Security boundary regressions using temporary repos and dummy credentials."""
import json
import subprocess

import pytest

from gai.common.git import add, unadd
from gai.common.git.core import GitError, _record_trace, get_traced_commands, set_tracing
from gai.common.llm.client import LLMError
from gai.common.llm.history import UsageRecord
from gai.history.commands import sanitize_argv
from gai.common.redact import redact_urls
from test_flow_resume import git, model  # noqa: F401
from test_sync_push_pull import _init_repo


@pytest.mark.parametrize("tracked", [False, True])
def test_add_directory_excludes_gai_even_without_gitignore(tmp_path, tracked, monkeypatch):
    _init_repo(tmp_path)
    folder = tmp_path / ".gai"
    folder.mkdir()
    log = folder / "commands.jsonl"
    log.write_text("old")
    (tmp_path / "[ab].txt").write_text("source")
    if tracked:
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-m", "initial")
        log.write_text("private new log")
        (tmp_path / "[ab].txt").write_text("new source")
    # The result must not depend on pathspec switches in the caller's shell.
    monkeypatch.setenv("GIT_LITERAL_PATHSPECS", "1")
    add(["."], cwd=tmp_path)
    monkeypatch.delenv("GIT_LITERAL_PATHSPECS")
    assert git(tmp_path, "diff", "--cached", "--name-only") == "[ab].txt"
    assert log.exists()


def test_unstage_in_unborn_repository_preserves_files_and_other_entries(tmp_path):
    _init_repo(tmp_path)
    for name in ("[ab].txt", "a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    add(["."], cwd=tmp_path)
    unadd(["[ab].txt"], cwd=tmp_path)
    assert git(tmp_path, "ls-files").splitlines() == ["a.txt", "b.txt"]
    assert (tmp_path / "[ab].txt").read_text() == "[ab].txt"
    unadd(["."], cwd=tmp_path)
    assert not git(tmp_path, "ls-files")
    assert all((tmp_path / name).exists() for name in ("[ab].txt", "a.txt", "b.txt"))


def test_splitflow_from_unborn_staged_repository(tmp_path, monkeypatch, model):
    from gai.cli import run
    from gai.flow import lib
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("source\n")
    git(tmp_path, "add", ".")
    monkeypatch.setattr(lib.Prompt, "ask", lambda *a, **k: "1")
    monkeypatch.setenv("GAI_USAGE_LOG", str(tmp_path / ".gai" / "usage.jsonl"))
    monkeypatch.setenv("GAI_HISTORY_LOG", str(tmp_path / ".gai" / "commands.jsonl"))
    assert run(["splitflow", "--yes", "--cn", "--no-push"]) == 0
    assert git(tmp_path, "ls-files").splitlines() == ["a.txt", "b.txt"]


def test_url_credentials_redacted_at_all_output_boundaries():
    url = "https://alice:swordfish@example.test/repo?access_token=private-query#private-fragment"
    expected = "https://***@example.test/repo?***#***"
    assert redact_urls(url) == expected
    assert redact_urls(expected) == expected
    set_tracing(True)
    try:
        _record_trace("fetch", url)
        trace = get_traced_commands()
    finally:
        set_tracing(False)
    llm = LLMError("request failed: " + url, detail=url)
    record = UsageRecord(ts="now", git_user="user", git_email="email", base_url=url)
    text = json.dumps([trace, str(GitError(url)), str(llm), llm.detail,
                       record.to_dict(), sanitize_argv(["config", "--base-url", url]),
                       sanitize_argv(["config", "--base-url=" + url])])
    assert "swordfish" not in text and "private-query" not in text and "private-fragment" not in text
    assert "example.test/repo" in text


def test_trace_redacts_credentials_before_shell_quoting():
    url = "https://alice:pass'word@example.test/repo"
    set_tracing(True)
    try:
        _record_trace("fetch", url)
        assert "pass" not in str(get_traced_commands())
        assert "word" not in str(get_traced_commands())
        assert "example.test/repo" in str(get_traced_commands())
    finally:
        set_tracing(False)
    assert "pass" not in str(GitError("unable to access '" + url + "': denied"))
