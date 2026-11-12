"""Push exactly the recorded commit and verify each actual push destination."""
import hashlib

import typer

from gai.cli_common import console
from gai.common.git import GitError, plan_push, run_git
from gai.flow.session import git_text


def targets(remote):
    return git_text("remote", "get-url", "--push", "--all", remote).splitlines()


def identity(plan, urls, head):
    return {"remote": plan.remote, "branch": plan.branch, "head": head,
            "url_hash": hashlib.sha256("\n".join(urls).encode()).hexdigest()}


def contains_commit(session, url, branch, head, number):
    # Inspect the push URL itself, which need not equal the fetch URL.
    ref = f"refs/heads/{branch}"
    result = run_git("ls-remote", "--exit-code", "--refs", "--", url, ref, trace=False)
    if result.returncode == 2:
        return False
    if result.returncode:
        raise GitError("无法核实推送目标 / Cannot inspect push destination", code="network")
    advertised = [parts[0] for line in result.stdout.splitlines()
                  if len(parts := line.split()) == 2 and parts[1] == ref]
    if not advertised:
        return False
    if head in advertised:
        return True
    local_ref = f"refs/gai/flows/{session.data['id']}/push-{number}"
    fetched = run_git("fetch", "--no-tags", "--no-write-fetch-head", "--", url,
                      f"+{ref}:{local_ref}", trace=False)
    if fetched.returncode:
        raise GitError("无法读取推送目标历史 / Cannot fetch push destination history", code="network")
    result = run_git("merge-base", "--is-ancestor", head, local_ref)
    if result.returncode not in (0, 1):
        raise GitError("无法比较推送目标历史 / Cannot compare push history")
    return result.returncode == 0


def push_exact(url, branch, head):
    result = run_git("push", "--", url, f"{head}:refs/heads/{branch}", trace=False)
    if result.returncode:
        from gai.common.git.remote import classify_remote_failure
        code = classify_remote_failure(result.stderr)
        raise GitError(f"推送失败，已保留检查点 / Push failed ({code}); checkpoint retained", code=code)


def push_flow(session, *, chinese, yes=False):
    from rich.prompt import Confirm
    session.verify()
    plan = plan_push(remote=session.data.get("remote"))
    urls = targets(plan.remote)
    if not urls:
        raise GitError("No push URL configured")
    head = session.data["observed"]["snapshot"]["head"]
    target = identity(plan, urls, head)
    previous = session.data.get("push_target")
    # Old checkpoints did not store the source SHA; still validate their target.
    if previous and any(previous.get(k) != target[k] for k in ("remote", "branch", "url_hash")):
        raise RuntimeError("推送目标已变化 / Push target changed; inspect the flow")
    if previous and previous.get("head", head) != head:
        raise RuntimeError("推送源提交已变化 / Push source commit changed")
    session.update(push_target=target)
    missing = [i for i, url in enumerate(urls)
               if not contains_commit(session, url, plan.branch, head, i)]
    if not missing:
        session.verify(strict=True)
        if targets(plan.remote) != urls:
            raise RuntimeError("推送地址已变化 / Push URL changed after verification")
        if plan.set_upstream:
            git_text("config", f"branch.{plan.branch}.remote", plan.remote)
            git_text("config", f"branch.{plan.branch}.merge", f"refs/heads/{plan.branch}")
        console.print("推送目标已包含本次提交 / Push destination already contains the saved commit")
        return
    console.print(f"Push: {head[:12]} → {plan.remote}/{plan.branch}", markup=False)
    if not yes and not Confirm.ask("确认推送到远程？" if chinese else "Push to remote?", default=True):
        raise typer.Exit(0)
    session.verify()
    if targets(plan.remote) != urls:
        raise RuntimeError("推送地址已变化 / Push URL changed after verification")
    for i in missing:
        session.verify()
        push_exact(urls[i], plan.branch, head)
        if not contains_commit(session, urls[i], plan.branch, head, i):
            raise GitError("推送结果尚未核实，请恢复后重查 / Push result not verified; resume to recheck")
        session.update(verified_push_targets=sorted(set(session.data.get("verified_push_targets", [])) | {i}))
    # Explicit SHA refspecs do not set upstream automatically.
    if plan.set_upstream:
        git_text("config", f"branch.{plan.branch}.remote", plan.remote)
        git_text("config", f"branch.{plan.branch}.merge", f"refs/heads/{plan.branch}")
    console.print("已核实推送结果 / Push verified")
