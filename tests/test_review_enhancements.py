"""Policy, coverage, branch review, archive browser and offline diagnostics."""
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from test_flow_resume import repo, model, git  # noqa: F401
from gai.cli import run
from gai.common.config import load_settings
from gai.common.git import list_change_entries, staged_snapshot, GitError
from gai.common.git.local import get_unstaged_diff
from gai.review import ReviewItem, ReviewResult, run_review
from gai.review.branch import load_branch_diff_info
from gai.review.library import records, compare, filter_records, browser
from gai.review.policy import enforce, options
from gai.flow.session import read_state


def fake_review(monkeypatch, findings=None, calls=None):
    def chat(self, *, system, user, **kwargs):
        if calls is not None:
            calls.append((system, user))
        return json.dumps({"review": findings or [], "summary": "change review", "commit_message": "fix: reviewed"})
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)


def critical():
    return {"severity": "critical", "file": "a.txt", "line": 1, "issue": "bug", "suggestion": "fix"}


def test_status_paths_and_external_edits(repo):
    git(repo, "config", "core.quotepath", "true")
    name = " 中文 空格.txt"
    (repo / name).write_text("data")
    assert name in {entry.path for entry in list_change_entries()}
    from gai.common.git import add
    add([name])
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"], cwd=repo).decode()
    assert name in staged.split("\0")
    git(repo, "mv", "b.txt", "重命名 文件.txt")
    assert "重命名 文件.txt" in {entry.path for entry in list_change_entries()}
    before, _ = get_unstaged_diff()
    (repo / "a.txt").write_text("external edit\n")
    after, _ = get_unstaged_diff()
    assert before != after and "external edit" in after


def test_repository_rules_and_override(repo, monkeypatch):
    (repo / ".gai.toml").write_text('[review]\nfail_on="critical"\nrequire_complete=true\n'
                                   'max_diff_chars=500\nignore_patterns=[]\nrules=["检查事务"]\n', encoding="utf-8")
    settings = load_settings()
    assert settings.fail_on == "critical" and settings.require_complete
    assert settings.review_rules == ("检查事务",) and settings.ignore_patterns == ()
    monkeypatch.setenv("GAI_MAX_DIFF_CHARS", "700")
    with options(fail_on="none", require_complete=False):
        settings = load_settings()
        assert settings.fail_on == "none" and not settings.require_complete and settings.max_diff_chars == 700
    assert load_settings().fail_on == "critical"


@pytest.mark.parametrize("text", ['[llm]\napi_key="bad"', '[review]\nfail_on=[]',
                                 '[review]\nrules="bad"', '[review]\nunknown=true'])
def test_invalid_repository_rules_rejected(repo, text):
    (repo / ".gai.toml").write_text(text)
    with pytest.raises(RuntimeError):
        load_settings()


def test_yes_commit_blocked_and_report_retained(repo, monkeypatch):
    git(repo, "add", "a.txt")
    head = git(repo, "rev-parse", "HEAD")
    fake_review(monkeypatch, [critical()])
    assert run(["commit", "--yes", "--fail-on", "critical", "--save-review"]) == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert records()[0]["result"]["status"] == "issues"
    assert records()[0]["commit"] is None


def test_invalid_policy_stops_before_unstaging(repo, monkeypatch):
    from gai.flow import lib
    git(repo, "add", "a.txt")
    before = staged_snapshot()
    monkeypatch.setattr(lib.Confirm, "ask", lambda *a, **k: pytest.fail("invalid policy must fail before prompts"))
    assert run(["splitflow", "--yes", "--fail-on", "misspelled"]) == 1
    assert staged_snapshot() == before
    assert read_state() is None


def test_auto_flow_policy_survives_resume(repo, model, monkeypatch):
    _, original = model
    def chat(self, *, system, user):
        if "expert code reviewer" in system:
            return json.dumps({"review": [critical()], "summary": "blocked", "commit_message": "fix: bad"})
        return original(self, system=system, user=user)
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    head = git(repo, "rev-parse", "HEAD")
    assert run(["splitflow", "--yes", "--cn", "--fail-on", "critical", "--no-push"]) == 1
    assert read_state()["review_options"]["fail_on"] == "critical"
    assert run(["splitflow", "--resume", "--cn"]) == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert run(["splitflow", "--resume", "--cn", "--fail-on", "none"]) == 0
    assert read_state()["phase"] == "done"


def test_chunked_review_covers_all_lines_and_preserves_index(repo, monkeypatch):
    lines = [f"line_{i:03d} " + "x" * 40 for i in range(60)]
    (repo / "a.txt").write_text("\n".join(lines) + "\n")
    git(repo, "add", "a.txt")
    (repo / ".gai.toml").write_text('[review]\nmax_diff_chars=600\nrules=["Check boundaries"]')
    calls = []
    fake_review(monkeypatch, calls=calls)
    before = staged_snapshot()
    result = run_review(chunked=True, review_only=True)
    assert staged_snapshot() == before
    assert len(calls) > 1 and result.coverage["state"] == "complete"
    assert all("Check boundaries" in system for system, _ in calls)
    assert all(any(line in prompt for _, prompt in calls) for line in lines)
    assert result.to_dict()["status"] == "passed"
    truncated = run_review(allow_truncated=True)
    assert truncated.to_dict()["status"] == "incomplete"
    assert truncated.coverage["partially_reviewed_files"] == ["a.txt"]
    with options(require_complete=True), pytest.raises(RuntimeError, match="Incomplete"):
        enforce(truncated)


def test_chunk_parser_failure_is_not_complete(repo, monkeypatch):
    (repo / "a.txt").write_text("line\n" * 200)
    git(repo, "add", "a.txt")
    (repo / ".gai.toml").write_text("[review]\nmax_diff_chars=400")
    count = 0
    def chat(*a, **k):
        nonlocal count
        count += 1
        return '{"review":[],"summary":"ok","commit_message":"fix: x"}' if count == 1 else "bad"
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    result = run_review(chunked=True)
    assert not result.parsed_ok and result.coverage["state"] == "failed"


def branch_setup(repo):
    git(repo, "restore", ".")
    git(repo, "switch", "-c", "feature")
    (repo / "feature.txt").write_text("COMMITTED_FEATURE\n")
    git(repo, "add", "feature.txt")
    git(repo, "commit", "-m", "feature")
    git(repo, "switch", "main")
    (repo / "main.txt").write_text("BASE_ONLY\n")
    git(repo, "add", "main.txt")
    git(repo, "commit", "-m", "main change")
    git(repo, "switch", "feature")


def test_branch_review_uses_merge_base_and_excludes_dirty_index(repo, monkeypatch):
    branch_setup(repo)
    (repo / "a.txt").write_text("DIRTY_INDEX\n")
    git(repo, "add", "a.txt")
    before = staged_snapshot()
    calls = []
    fake_review(monkeypatch, calls=calls)
    assert run(["review", "--base", "main", "--save-review", "--json"]) == 0
    assert staged_snapshot() == before
    prompt = calls[0][1]
    assert "COMMITTED_FEATURE" in prompt and "BASE_ONLY" not in prompt and "DIRTY_INDEX" not in prompt
    record = records()[0]
    assert record["result"]["scope"]["kind"] == "branch"
    assert record["staged_files"] == ["feature.txt"] and record["commit"] is None
    assert filter_records([record], commit=before.head[:8])


def test_branch_move_during_review_rejected(repo, monkeypatch):
    branch_setup(repo)
    info = load_branch_diff_info("main")
    def chat(*a, **k):
        git(repo, "update-ref", "refs/heads/main", "HEAD")
        return '{"review":[],"summary":"ok","commit_message":"fix: x"}'
    monkeypatch.setattr("gai.common.llm.client.LLMClient.chat", chat)
    with pytest.raises(GitError, match="changed"):
        run_review(diff_info=info)


def test_library_compare_filter_and_html_escape(repo, monkeypatch):
    fake_review(monkeypatch, [critical()])
    git(repo, "add", "a.txt")
    assert run(["review", "--save-review"]) == 0
    old = records()[0]
    new = {**old, "id": "f" * 32, "title": "</script><img src=x onerror=alert(1)>",
           "result": {**old["result"], "review": []}}
    changes = compare(old, new)
    assert len(changes["pending_resolution"]) == 1 and not changes["new"]
    assert filter_records([old, new], severity="critical") == [old]
    page = browser([old, new]).read_text(encoding="utf-8")
    assert "</script><img" not in page and "\\u003c/script" in page
    script = page.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    target = repo / "browser-check.js"
    target.write_text(script, encoding="utf-8")
    subprocess.run(["node", "--check", str(target)], check=True, capture_output=True)
    ui_test = Path(__file__).with_name("test_review_library_ui.js")
    checked = subprocess.run(["node", str(ui_test), str(repo / ".gai/reviews/browser.html")],
                             check=True, capture_output=True, text=True)
    assert "interactions OK" in checked.stdout
    assert run(["reviews", "show", old["id"][:10]]) == 0
    assert run(["reviews", "compare", old["id"], old["id"]]) == 0


def test_doctor_offline_and_online_redaction(repo, monkeypatch):
    from gai.setup import doctor
    monkeypatch.setenv("GAI_API_KEY", "PRIVATE_KEY_VALUE")
    monkeypatch.setenv("GAI_MODEL", "private-test-model")
    def blocked(*a, **k):
        pytest.fail("offline doctor must not access HTTP")
    monkeypatch.setattr(doctor.httpx, "get", blocked)
    result = doctor.diagnose()
    assert any(r["check"] == "network" and r["status"] == "skipped" for r in result)
    assert "PRIVATE_KEY_VALUE" not in json.dumps(result)
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **k: httpx.Response(
        401, json={"error": "PRIVATE_KEY_VALUE"}))
    result = doctor.diagnose(network=True)
    assert any(r["check"] == "model_api" and r["status"] == "error" for r in result)
    assert "PRIVATE_KEY_VALUE" not in json.dumps(result)
