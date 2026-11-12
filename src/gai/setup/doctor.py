"""Opt-in connectivity diagnostics; local checks never request credentials."""
import os
import shutil
import subprocess

import httpx
import typer

from gai.cli_common import app, console
from gai.common.i18n import H
from gai.common.git import run_git, ensure_repo, GitError


def diagnose(network=False, remote="origin"):
    rows = []
    def add(name, status, detail):
        rows.append({"check": name, "status": status, "detail": detail})
    if not shutil.which("git"):
        add("git", "error", "Git 未安装或不在 PATH / Git not found on PATH")
        return rows
    try:
        version = run_git("--version", trace=False)
    except (GitError, ValueError):
        add("git", "error", "Git 无法启动 / Cannot start Git")
        return rows
    add("git", "ok" if not version.returncode else "error", version.stdout.strip())
    root = None
    try:
        root = ensure_repo()
        add("repository", "ok", str(root))
        metadata = run_git("rev-parse", "--absolute-git-dir", trace=False)
        writable = os.access(root, os.W_OK) and os.access(metadata.stdout.strip(), os.W_OK)
        add("local_permissions", "ok" if writable else "warning",
            "本地写权限预检，不代表远程推送权限 / Local access hint only; remote write access is not verified")
        status = run_git("ls-files", "-u", trace=False)
        add("conflicts", "warning" if status.stdout else "ok",
            "存在未解决冲突 / Unresolved conflicts" if status.stdout else "无未解决冲突 / No unresolved conflicts")
        from gai.flow.session import read_state
        state = read_state(allow_backup=True)
        active = state and state.get("phase") not in {"done", "aborted"}
        add("flow", "warning" if active else "ok",
            f"未完成流程 / Resume: gai {state['kind']} --resume" if active else "无未完成流程 / No unfinished flow")
    except (GitError, RuntimeError, OSError, ValueError):
        add("repository_or_flow", "warning", "仓库或检查点需要检查 / Inspect repository and flow checkpoint")
    settings = None
    try:
        from gai.common.config import load_settings
        settings = load_settings()
        add("model", "ok" if settings.api_key else "error",
            f"{settings.model}; " + ("已配置密钥 / Key configured" if settings.api_key else "未配置密钥 / Key missing"))
        add("review_policy", "ok", f"fail_on={settings.fail_on}, require_complete={settings.require_complete}")
    except (RuntimeError, ValueError, OSError, GitError):
        add("configuration", "error", "配置无法读取，请检查个人配置和 .gai.toml / Invalid configuration")
    if not network:
        add("network", "skipped", "联网诊断需显式指定 --network / Use --network to check connectivity")
        return rows
    if settings and settings.api_key:
        try:
            response = httpx.get(settings.base_url + "/models",
                                 headers={"Authorization": "Bearer " + settings.api_key},
                                 timeout=10, follow_redirects=False)
            if response.status_code in {404, 405}:
                add("model_api", "warning", "服务商不支持模型列表，不能据此判断模型不可用 / Model listing unsupported")
            elif response.status_code != 200:
                add("model_api", "error", f"HTTP {response.status_code}; 检查鉴权或服务地址 / Check credentials and endpoint")
            else:
                data = response.json()
                models = {item.get("id") for item in data.get("data", []) if isinstance(item, dict)}
                found = settings.model in models
                add("model_api", "ok" if found else "warning",
                    "模型在服务商列表中 / Model listed" if found else
                    "列表未找到配置模型；检查准确名称，列表不一定完整 / Model not listed; verify exact name")
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            add("model_api", "error", "连接失败或响应无法识别 / Connection or response error")
    if root:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        try:
            if remote.startswith("-"):
                raise ValueError("Invalid remote")
            configured = run_git("remote", trace=False).stdout.splitlines()
            if remote not in configured:
                raise ValueError("Remote not configured")
            result = subprocess.run(["git", "ls-remote", "--heads", remote], env=env, timeout=15,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            add("remote_read", "ok" if not result.returncode else "error",
                "仅检查远程读取，不证明推送权限 / Read connectivity only; push permission is not verified")
        except (GitError, ValueError, OSError, subprocess.TimeoutExpired):
            add("remote_read", "error", "远程读取失败，请检查远程配置和凭据 / Check remote and credentials")
    return rows


@app.command("doctor", help=H("Diagnose Git, configuration and saved flows.", "诊断 Git、配置及未完成流程。"))
def doctor_cmd(
    network: bool = typer.Option(False, "--network", help=H("Also check model listing and remote read access.", "同时检查模型列表与远程读取权限。")),
    remote: str = typer.Option("origin", "--remote", help=H("Remote to check.", "要检查的远程名。")),
    as_json: bool = typer.Option(False, "--json", help=H("Print JSON.", "输出 JSON。")),
    cn: bool = typer.Option(False, "--cn"),
):
    rows = diagnose(network, remote)
    if as_json:
        console.print_json(data=rows)
    else:
        for row in rows:
            console.print(f"[{row['status']}] {row['check']}: {row['detail']}", markup=False)
    if any(row["status"] == "error" for row in rows):
        raise typer.Exit(1)
