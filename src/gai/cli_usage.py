"""Friendly CLI usage errors: wrong subcommand / option typos / missing dashes."""

from __future__ import annotations

import difflib
import re
from typing import Iterable

import click
from click.exceptions import NoSuchOption, UsageError

# Subcommand → (command, English what-it-does, Chinese what-it-does)
_COMMAND_EXAMPLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "add": (
        ("gai add", "Stage all changes in the current directory", "暂存当前目录全部变更"),
        ("gai add src/", "Stage files under src/", "暂存 src/ 目录下的文件"),
        ("gai add --cn -t", "Stage with Chinese tips and print git trace", "中文提示暂存，并打印 git 链路"),
    ),
    "unadd": (
        ("gai unadd --cn", "Unstage all staged files (asks for confirmation)", "撤销全部暂存（需确认）"),
        ("gai unadd src/", "Unstage files under src/", "撤销 src/ 下的暂存"),
    ),
    "uncommit": (
        ("gai uncommit --cn", "Soft-undo the latest commit (keeps changes staged)", "软撤销最近一次提交（改动仍保留在暂存区）"),
    ),
    "review": (
        ("gai review --cn", "AI-review staged changes only (no commit)", "仅审查已暂存变更（不提交）"),
        ("gai review --json", "Output the review result as JSON", "以 JSON 输出审查结果"),
    ),
    "commit": (
        ("gai commit --cn", "Review → suggest message → confirm → commit", "审查 → 建议提交信息 → 确认 → 提交"),
        ("gai commit -y --cn", "Commit with defaults, skip interactive confirm", "按默认流程提交，跳过交互确认"),
        ("gai commit --cn --push", "Commit then push to the configured remote", "提交成功后推送到已配置的远程"),
        (
            'gai commit -m "fix: handle nil" --no-ai',
            "Commit with a given message, skip AI",
            "使用指定信息提交，跳过 AI",
        ),
    ),
    "push": (
        ("gai push --cn", "Push current branch (checks there is something to push)", "推送当前分支（先检查是否有可推送内容）"),
        ("gai push -y --cn", "Push without interactive confirmation", "推送并跳过交互确认"),
        ("gai push -r origin -u --cn", "Push to origin and set upstream tracking", "推送到 origin 并设置上游跟踪"),
    ),
    "pull": (
        ("gai pull --cn", "Pull after checking remote has updates (asks to confirm)", "检查远程有更新后确认再拉取"),
        ("gai pull -y --cn", "Pull without interactive confirmation", "拉取并跳过交互确认"),
    ),
    "report": (
        ("gai report --cn", "Summarize recent commits into a work report", "根据近期提交生成工作总结"),
        ("gai report --since 7d --cn", "Report covering the last 7 days", "统计最近 7 天的提交"),
        (
            "gai report --since 2026-09-01 --until 2026-09-20 --cn",
            "Report for an explicit date range",
            "按指定起止日期生成报告",
        ),
        (
            "gai report --alltime --author me --cn",
            "Full-history report for the current git user",
            "当前用户的全部历史提交总结",
        ),
    ),
    "config": (
        ("gai config --show --cn", "Show effective config (secrets masked)", "查看当前生效配置（密钥已掩码）"),
        ("gai config --api-key <key>", "Save API key to ~/.gai/config.toml", "把 API Key 写入 ~/.gai/config.toml"),
    ),
}


def _example_lines(command: str, *, chinese: bool, limit: int = 3) -> list[str]:
    """Format '正确示例/Correct examples' lines with what each command does."""
    items = _COMMAND_EXAMPLES.get(command, ())
    if not items:
        return []
    header = "正确示例：" if chinese else "Correct examples:"
    lines = [header]
    for cmd, en, cn in items[:limit]:
        desc = cn if chinese else en
        lines.append(f"  {cmd}  —  {desc}")
    return lines


def want_chinese(argv: Iterable[str] | None = None) -> bool:
    args = list(argv) if argv is not None else []
    return "--cn" in args


def close_matches(token: str, choices: Iterable[str], *, n: int = 3) -> list[str]:
    choices_list = list(choices)
    stripped = token.lstrip("-")
    norm_map: dict[str, str] = {}
    for c in choices_list:
        norm_map[c.lstrip("-").lower()] = c
        norm_map[c.lower()] = c
    hits = difflib.get_close_matches(
        token.lower(),
        list(norm_map.keys()),
        n=n,
        cutoff=0.5,
    )
    if stripped and stripped.lower() != token.lower():
        hits += difflib.get_close_matches(
            stripped.lower(),
            list(norm_map.keys()),
            n=n,
            cutoff=0.5,
        )
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        opt = norm_map.get(h, h)
        if opt not in seen:
            seen.add(opt)
            out.append(opt)
    return out[:n]


def suggest_flags_for_token(token: str, option_flags: list[str], *, n: int = 5) -> list[str]:
    """Prefer exact stem / prefix matches, then fuzzy close matches."""
    if not token:
        return []
    raw = token.strip()
    stem = raw.lstrip("-").lower()
    stems: dict[str, list[str]] = {}
    for f in option_flags:
        stems.setdefault(f.lstrip("-").lower(), []).append(f)

    out: list[str] = []

    def _add(flag: str) -> None:
        if flag and flag not in out:
            out.append(flag)

    # Exact stem: yes → --yes (prefer long form)
    if stem in stems:
        for f in sorted(stems[stem], key=lambda x: (not x.startswith("--"), len(x))):
            _add(f)

    # Prefix stem match (yess → yes); require meaningful overlap
    if len(stem) >= 2:
        for s, flags in stems.items():
            if s.startswith(stem) or (len(s) >= 2 and stem.startswith(s)):
                for f in flags:
                    _add(f)

    # Single-dash long form: -yes → --yes
    if re.fullmatch(r"-[A-Za-z][A-Za-z0-9-]{1,}", raw):
        doubled = "-" + raw
        if doubled in option_flags:
            _add(doubled)

    for m in close_matches(raw, option_flags, n=n):
        _add(m)
    if stem:
        for m in close_matches(f"--{stem}", option_flags, n=n):
            _add(m)

    return out[:n]


def collect_option_flags(command: click.Command | None) -> list[str]:
    if command is None:
        return []
    flags: list[str] = []
    for param in getattr(command, "params", []) or []:
        opts = getattr(param, "opts", None)
        secondary = getattr(param, "secondary_opts", None)
        # Duck-type Click/Typer Option (typer vendors its own Option class)
        if opts:
            flags.extend(list(opts))
        if secondary:
            flags.extend(list(secondary))
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _extract_bad_command(message: str) -> str | None:
    m = re.search(r"No such command ['\"]([^'\"]+)['\"]", message)
    return m.group(1) if m else None


def _extract_bad_option(message: str, exc: BaseException) -> str | None:
    if isinstance(exc, NoSuchOption) and getattr(exc, "option_name", None):
        return str(exc.option_name)
    m = re.search(r"No such option:\s*(\S+)", message)
    return m.group(1) if m else None


def _extract_extra_args(message: str) -> list[str]:
    m = re.search(r"unexpected extra argument\(s\)\s*\(([^)]+)\)", message, re.I)
    if not m:
        return []
    return [a.strip() for a in m.group(1).split() if a.strip()]


def format_usage_error(
    exc: BaseException,
    *,
    argv: list[str] | None = None,
    root: click.Group | None = None,
    chinese: bool | None = None,
) -> str:
    """Build a friendly usage error with suggestions and correct examples."""
    argv = list(argv or [])
    chinese = want_chinese(argv) if chinese is None else chinese
    message = str(exc).strip()

    commands = list(_COMMAND_EXAMPLES.keys())
    if root is not None:
        try:
            commands = sorted(set(commands) | set(root.list_commands(click.Context(root))))
        except Exception:
            pass

    # Resolve which subcommand user attempted (first non-flag token)
    tokens = [a for a in argv if a != "--"]
    invoked_cmd: str | None = None
    for a in tokens:
        if a.startswith("-"):
            continue
        invoked_cmd = a
        break

    lines: list[str] = []

    # --- unknown command ---
    bad_cmd = _extract_bad_command(message)
    if bad_cmd or "No such command" in message:
        token = bad_cmd or (invoked_cmd or "")
        suggestions = close_matches(token, commands) if token else []
        if chinese:
            lines.append(f"未知子命令：{token!r}" if token else "未知子命令。")
            if suggestions:
                lines.append("你是否想执行：" + "、".join(f"`{s}`" for s in suggestions))
            target = suggestions[0] if suggestions else None
            if target and target in _COMMAND_EXAMPLES:
                lines.extend(_example_lines(target, chinese=True, limit=3))
            else:
                lines.append("可用子命令：" + "、".join(commands))
                lines.append("查看帮助：gai -h --cn")
        else:
            lines.append(f"Unknown command: {token!r}" if token else "Unknown command.")
            if suggestions:
                lines.append("Did you mean: " + ", ".join(f"`{s}`" for s in suggestions))
            target = suggestions[0] if suggestions else None
            if target and target in _COMMAND_EXAMPLES:
                lines.extend(_example_lines(target, chinese=False, limit=3))
            else:
                lines.append("Available commands: " + ", ".join(commands))
                lines.append("See help: gai -h")
        return "\n".join(lines)

    # Resolve click Command for option suggestions
    cmd_obj: click.Command | None = None
    if root is not None and invoked_cmd and invoked_cmd in set(commands):
        try:
            cmd_obj = root.get_command(click.Context(root), invoked_cmd)
        except Exception:
            cmd_obj = None

    option_flags = collect_option_flags(cmd_obj)
    # Common globals (only if missing) — keep after command flags so suggestions prefer command opts
    for g in ("--cn", "--trace", "-t", "-h", "--help"):
        if g not in option_flags:
            option_flags.append(g)

    # --- unknown option ---
    bad_opt = _extract_bad_option(message, exc)
    if bad_opt or type(exc).__name__ == "NoSuchOption" or message.startswith("No such option"):
        token = bad_opt or ""
        fixed_double = None
        if re.fullmatch(r"-[A-Za-z][A-Za-z0-9-]{1,}", token):
            fixed_double = "-" + token  # -yes → --yes

        suggestions = suggest_flags_for_token(token, option_flags)
        if fixed_double and fixed_double not in suggestions:
            suggestions = [fixed_double, *suggestions]

        if chinese:
            lines.append(f"未知参数：{token}" if token else "未知参数。")
            if fixed_double:
                lines.append(
                    f"长参数需要两个短横线，请写成 `{fixed_double}` "
                    f"（你写的是单横线 `{token}`）。"
                )
            if suggestions:
                lines.append("你是否想使用：" + "、".join(f"`{s}`" for s in suggestions))
            if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
                lines.extend(_example_lines(invoked_cmd, chinese=True, limit=3))
            lines.append(f"查看该命令帮助：gai {invoked_cmd or '<command>'} -h --cn")
        else:
            lines.append(f"Unknown option: {token}" if token else "Unknown option.")
            if fixed_double:
                lines.append(
                    f"Long options need two dashes: use `{fixed_double}` "
                    f"(you used a single dash `{token}`)."
                )
            if suggestions:
                lines.append("Did you mean: " + ", ".join(f"`{s}`" for s in suggestions))
            if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
                lines.extend(_example_lines(invoked_cmd, chinese=False, limit=3))
            lines.append(f"See help: gai {invoked_cmd or '<command>'} -h")
        return "\n".join(lines)

    # --- unexpected extra args (often missing --) ---
    extras = _extract_extra_args(message)
    if extras or "unexpected extra argument" in message.lower():
        extras = extras or [a for a in tokens[1:] if not a.startswith("-")]
        uniq: list[str] = []
        for extra in extras:
            for flag in suggest_flags_for_token(extra, option_flags):
                if flag not in uniq:
                    uniq.append(flag)

        if chinese:
            lines.append(
                "出现了多余参数："
                + "、".join(repr(e) for e in extras)
                + "。选项名通常需要以 `-` / `--` 开头。"
            )
            if uniq:
                lines.append("你是否想使用：" + "、".join(f"`{s}`" for s in uniq[:5]))
                if invoked_cmd:
                    lines.append(f"正确示例：gai {invoked_cmd} {uniq[0]}")
            if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
                lines.append("更多示例：")
                for cmd, _en, cn in _COMMAND_EXAMPLES[invoked_cmd][:2]:
                    lines.append(f"  {cmd}  —  {cn}")
            lines.append(f"查看帮助：gai {invoked_cmd or '-h'} -h --cn")
        else:
            lines.append(
                "Unexpected argument(s): "
                + ", ".join(repr(e) for e in extras)
                + ". Option names usually start with `-` / `--`."
            )
            if uniq:
                lines.append("Did you mean: " + ", ".join(f"`{s}`" for s in uniq[:5]))
                if invoked_cmd:
                    lines.append(f"Correct example: gai {invoked_cmd} {uniq[0]}")
            if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
                lines.append("More examples:")
                for cmd, en, _cn in _COMMAND_EXAMPLES[invoked_cmd][:2]:
                    lines.append(f"  {cmd}  —  {en}")
            lines.append(f"See help: gai {invoked_cmd or '-h'} -h")
        return "\n".join(lines)

    # --- fallback ---
    if chinese:
        lines.append(f"命令用法有误：{message}")
        lines.append("可用子命令：" + "、".join(commands))
        if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
            lines.extend(_example_lines(invoked_cmd, chinese=True, limit=3))
        lines.append("查看帮助：gai -h --cn")
    else:
        lines.append(f"Usage error: {message}")
        lines.append("Available commands: " + ", ".join(commands))
        if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
            lines.extend(_example_lines(invoked_cmd, chinese=False, limit=3))
        lines.append("See help: gai -h")
    return "\n".join(lines)
