"""Friendly CLI usage errors: wrong subcommand / option typos / missing dashes."""

from __future__ import annotations

import difflib
import re
from typing import Iterable

import click
from click.exceptions import NoSuchOption, UsageError

# Subcommand → short correct examples (EN / 简体中文)
_COMMAND_EXAMPLES: dict[str, tuple[str, ...]] = {
    "add": (
        "gai add",
        "gai add src/",
        "gai add --cn -t",
    ),
    "unadd": (
        "gai unadd --cn",
        "gai unadd src/",
    ),
    "uncommit": (
        "gai uncommit --cn",
    ),
    "review": (
        "gai review --cn",
        "gai review --json",
    ),
    "commit": (
        "gai commit --cn",
        "gai commit -y --cn",
        "gai commit --cn --push",
        "gai commit -m \"fix: handle nil\" --no-ai",
    ),
    "push": (
        "gai push --cn",
        "gai push -y --cn",
        "gai push -r origin -u --cn",
    ),
    "pull": (
        "gai pull --cn",
        "gai pull -y --cn",
    ),
    "report": (
        "gai report --cn",
        "gai report --since 7d --cn",
        "gai report --since 2026-09-01 --until 2026-09-20 --cn",
        "gai report --alltime --author me --cn",
    ),
    "config": (
        "gai config --show --cn",
        "gai config --api-key <key>",
    ),
}

_COMMON_OPTION_EXAMPLES: tuple[str, ...] = (
    "--cn",
    "-t / --trace",
    "-h / --help",
    "-y / --yes",
)


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
                lines.append("正确示例：")
                for ex in _COMMAND_EXAMPLES[target][:3]:
                    lines.append(f"  {ex}")
            else:
                lines.append("可用子命令：" + "、".join(commands))
                lines.append("查看帮助：gai -h --cn")
        else:
            lines.append(f"Unknown command: {token!r}" if token else "Unknown command.")
            if suggestions:
                lines.append("Did you mean: " + ", ".join(f"`{s}`" for s in suggestions))
            target = suggestions[0] if suggestions else None
            if target and target in _COMMAND_EXAMPLES:
                lines.append("Correct examples:")
                for ex in _COMMAND_EXAMPLES[target][:3]:
                    lines.append(f"  {ex}")
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
                lines.append("正确示例：")
                for ex in _COMMAND_EXAMPLES[invoked_cmd][:3]:
                    lines.append(f"  {ex}")
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
                lines.append("Correct examples:")
                for ex in _COMMAND_EXAMPLES[invoked_cmd][:3]:
                    lines.append(f"  {ex}")
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
                for ex in _COMMAND_EXAMPLES[invoked_cmd][:2]:
                    lines.append(f"  {ex}")
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
                for ex in _COMMAND_EXAMPLES[invoked_cmd][:2]:
                    lines.append(f"  {ex}")
            lines.append(f"See help: gai {invoked_cmd or '-h'} -h")
        return "\n".join(lines)

    # --- fallback ---
    if chinese:
        lines.append(f"命令用法有误：{message}")
        lines.append("可用子命令：" + "、".join(commands))
        if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
            lines.append("正确示例：")
            for ex in _COMMAND_EXAMPLES[invoked_cmd][:3]:
                lines.append(f"  {ex}")
        lines.append("查看帮助：gai -h --cn")
    else:
        lines.append(f"Usage error: {message}")
        lines.append("Available commands: " + ", ".join(commands))
        if invoked_cmd and invoked_cmd in _COMMAND_EXAMPLES:
            lines.append("Correct examples:")
            for ex in _COMMAND_EXAMPLES[invoked_cmd][:3]:
                lines.append(f"  {ex}")
        lines.append("See help: gai -h")
    return "\n".join(lines)
