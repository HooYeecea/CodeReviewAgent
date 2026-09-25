"""User-facing error messages (EN / 简体中文)."""

from __future__ import annotations

from gai.git_ops import GitError
from gai.llm.client import LLMError


# --- LLM ---

_LLM_MESSAGES: dict[str, tuple[str, str]] = {
    "missing_key": (
        "API key not configured. Set GAI_API_KEY / OPENAI_API_KEY "
        "or run: gai config --api-key <key>",
        "未配置 API Key。请设置环境变量 GAI_API_KEY / OPENAI_API_KEY，"
        "或运行：gai config --api-key <key>",
    ),
    "unauthorized": (
        "API authentication failed (invalid or expired API key). "
        "Check the key with `gai config --show` or reset via `gai config --api-key <key>`.",
        "API 鉴权失败（Key 无效或已过期）。请用 `gai config --show` 检查，"
        "或运行 `gai config --api-key <key>` 重新设置。",
    ),
    "billing": (
        "LLM provider rejected the request due to billing/quota "
        "(insufficient balance or plan limit). Top up or upgrade your plan, then retry.",
        "大模型服务因欠费或配额不足拒绝请求。请充值或升级套餐后重试。",
    ),
    "rate_limit": (
        "LLM rate limit exceeded. Wait a moment and retry "
        "(or lower request frequency).",
        "触发大模型限流。请稍后再试，或降低调用频率。",
    ),
    "forbidden": (
        "LLM API forbidden this request (no permission for this model/endpoint).",
        "大模型 API 拒绝访问（当前 Key 无此模型或接口权限）。",
    ),
    "not_found": (
        "LLM API endpoint or model not found. Check --model / base_url in config.",
        "大模型接口或模型不存在。请检查配置中的 model / base_url。",
    ),
    "server": (
        "LLM service is temporarily unavailable. Retry later.",
        "大模型服务暂时不可用，请稍后重试。",
    ),
    "timeout": (
        "LLM request timed out. Try again, or raise timeout via "
        "`gai config --timeout <seconds>`.",
        "调用大模型超时。请重试，或用 `gai config --timeout <秒>` 调大超时。",
    ),
    "network": (
        "Network error while calling the LLM. Check connectivity / proxy / base_url.",
        "调用大模型时网络异常。请检查网络、代理或配置中的 base_url。",
    ),
    "empty": (
        "LLM returned empty content. Retry, or switch model.",
        "大模型返回了空内容。请重试，或更换模型。",
    ),
    "bad_response": (
        "Unexpected LLM response format. Retry, or switch model.",
        "大模型返回格式异常。请重试，或更换模型。",
    ),
    "api": (
        "LLM API request failed.",
        "大模型 API 请求失败。",
    ),
}

# --- Git / repo ---

_GIT_MESSAGES: dict[str, tuple[str, str]] = {
    "no_git": (
        "git executable not found on PATH. Install Git and reopen the terminal.",
        "系统 PATH 中找不到 git。请安装 Git 后重新打开终端。",
    ),
    "not_repo": (
        "Not a git repository. cd into a repo, or run `git init` first.",
        "当前目录不是 git 仓库。请进入仓库目录，或先执行 `git init`。",
    ),
    "no_remote": (
        "No git remote configured. Add one first, e.g. "
        "`git remote add origin <url>`.",
        "尚未配置远程仓库。请先添加，例如：`git remote add origin <url>`。",
    ),
    "remote_not_found": (
        "Specified remote was not found. Pass an existing name with -r/--remote.",
        "指定的远程名不存在。请用 -r/--remote 传入已有远程名。",
    ),
    "multiple_remotes": (
        "Multiple remotes found and none named 'origin'. "
        "Pass -r/--remote explicitly.",
        "存在多个远程且没有名为 origin 的。请显式传入 -r/--remote。",
    ),
    "detached_head": (
        "HEAD is detached. Checkout a branch before push/pull.",
        "当前处于 detached HEAD。请先 checkout 到分支再推送/拉取。",
    ),
    "no_upstream": (
        "Branch has no upstream. Re-run with --set-upstream, "
        "or omit --no-set-upstream.",
        "当前分支没有上游。请加 --set-upstream，或不要使用禁止设上游的选项。",
    ),
    "nothing_staged": (
        "Nothing staged. Run `gai add` / `gai add .` first.",
        "没有已暂存变更。请先运行 `gai add` / `gai add .`。",
    ),
    "filtered_empty": (
        "Staged changes are empty after ignore filters. "
        "Adjust ignore_patterns or stage other files.",
        "暂存内容在忽略规则过滤后为空。请调整 ignore_patterns，或暂存其他文件。",
    ),
    "nothing_to_unadd": (
        "Nothing staged; nothing to unadd.",
        "没有已暂存变更，无需撤销。",
    ),
    "no_commit": (
        "No commit to undo (repository has no commits?).",
        "没有可撤销的提交（仓库可能尚无提交）。",
    ),
    "empty_message": (
        "Commit message must not be empty.",
        "提交信息不能为空。",
    ),
    "no_author": (
        "Cannot resolve current git user. Set user.email/user.name "
        "or pass --author explicitly.",
        "无法解析当前 git 用户。请设置 user.email/user.name，或显式传入 --author。",
    ),
    "auth": (
        "Remote authentication failed. Check SSH keys / HTTPS credentials.",
        "远程仓库鉴权失败。请检查 SSH 密钥或 HTTPS 凭证。",
    ),
    "rejected": (
        "Remote rejected the update (non-fast-forward or protected branch). "
        "Pull/rebase first, or check branch protection.",
        "远程拒绝更新（非快进或受保护分支）。请先拉取/变基，或检查分支保护规则。",
    ),
    "network": (
        "Network error talking to the remote. Check connectivity / proxy / remote URL.",
        "连接远程仓库时网络异常。请检查网络、代理或 remote URL。",
    ),
    "fetch_failed": (
        "git fetch failed.",
        "git fetch 失败。",
    ),
    "push_failed": (
        "git push failed.",
        "git push 失败。",
    ),
    "pull_failed": (
        "git pull failed.",
        "git pull 失败。",
    ),
    "add_failed": (
        "git add failed.",
        "git add 失败。",
    ),
    "commit_failed": (
        "git commit failed.",
        "git commit 失败。",
    ),
    "unadd_failed": (
        "git restore --staged failed.",
        "取消暂存失败（git restore --staged）。",
    ),
    "uncommit_failed": (
        "git reset --soft failed.",
        "撤销提交失败（git reset --soft）。",
    ),
    "log_failed": (
        "git log failed.",
        "git log 失败。",
    ),
    "generic": (
        "Git operation failed.",
        "Git 操作失败。",
    ),
}

# --- Period / report ---

_PERIOD_MESSAGES: dict[str, tuple[str, str]] = {
    "since_after_until": (
        "Invalid period: --since ({since}) is later than --until ({until}). "
        "Start time must not be after end time. "
        "Example: --since 2026-09-01 --until 2026-09-20",
        "时间范围无效：--since（{since}）晚于 --until（{until}）。开始时间不能晚于结束时间。"
        "正确示例：--since 2026-09-01 --until 2026-09-20",
    ),
    "invalid_since": (
        "Invalid --since date: {value!r}. "
        "Correct formats: YYYY-MM-DD (e.g. 2026-09-01), "
        "relative N[dwmy] (e.g. 7d / 2w / 1m / 1y), or alltime.",
        "无效的 --since 日期：{value!r}。"
        "正确格式：YYYY-MM-DD（如 2026-09-01）、"
        "相对时间 N[dwmy]（如 7d / 2w / 1m / 1y），或 alltime。",
    ),
    "invalid_until": (
        "Invalid --until date: {value!r}. "
        "Correct formats: YYYY-MM-DD (e.g. 2026-09-20), "
        "or a git-compatible date string.",
        "无效的 --until 日期：{value!r}。"
        "正确格式：YYYY-MM-DD（如 2026-09-20），"
        "或 git 可识别的日期字符串。",
    ),
    "no_commits": (
        "No commits found in the selected range. "
        "Try a wider --since / --alltime or drop --author. "
        "Example: --since 14d  or  --since 2026-09-01 --until 2026-09-20",
        "所选时间范围内没有提交。请扩大 --since / 使用 --alltime，或去掉 --author。"
        "正确示例：--since 14d  或  --since 2026-09-01 --until 2026-09-20",
    ),
}


class PeriodError(ValueError):
    """Raised when --since/--until validation fails."""

    def __init__(self, code: str, **fmt: object) -> None:
        self.code = code
        self.fmt = fmt
        en, _ = _PERIOD_MESSAGES.get(code, (str(code), str(code)))
        try:
            super().__init__(en.format(**fmt))
        except (KeyError, ValueError):
            super().__init__(en)


def _pick(pair: tuple[str, str], chinese: bool, **fmt: object) -> str:
    text = pair[1] if chinese else pair[0]
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (KeyError, ValueError):
        return text


def format_cli_error(exc: BaseException, *, chinese: bool = False) -> str:
    """Turn an exception into a friendly user-facing message."""
    if isinstance(exc, PeriodError):
        pair = _PERIOD_MESSAGES.get(exc.code)
        if pair:
            return _pick(pair, chinese, **exc.fmt)
        return str(exc)

    if isinstance(exc, LLMError):
        kind = exc.kind or "api"
        pair = _LLM_MESSAGES.get(kind) or _LLM_MESSAGES["api"]
        msg = _pick(pair, chinese)
        if kind in {"api", "server", "forbidden", "not_found"} and exc.status_code:
            msg = f"{msg} (HTTP {exc.status_code})"
        return msg

    if isinstance(exc, GitError):
        code = exc.code or "generic"
        pair = _GIT_MESSAGES.get(code)
        if pair:
            msg = _pick(pair, chinese)
            raw = str(exc).strip()
            if code in {"remote_not_found", "multiple_remotes"} and raw:
                if chinese and "Available:" in raw:
                    avail = raw.split("Available:", 1)[1].strip()
                    return f"{msg} 可用：{avail}"
                if not chinese:
                    return raw
            if code in {
                "push_failed",
                "pull_failed",
                "fetch_failed",
                "auth",
                "rejected",
                "network",
                "generic",
                "commit_failed",
                "add_failed",
                "log_failed",
            } and raw:
                detail = raw if len(raw) <= 240 else raw[:240] + "…"
                # Avoid duplicating when message already is the detail
                if detail and detail.lower() not in msg.lower():
                    return f"{msg}\n  → {detail}"
            return msg
        return str(exc)

    # Legacy RuntimeError strings from review/report
    text = str(exc)
    lowered = text.lower()
    if "no staged changes" in lowered:
        return _pick(_GIT_MESSAGES["nothing_staged"], chinese)
    if "empty after ignore" in lowered:
        return _pick(_GIT_MESSAGES["filtered_empty"], chinese)
    if "no commits found" in lowered:
        return _pick(_PERIOD_MESSAGES["no_commits"], chinese)
    return text
