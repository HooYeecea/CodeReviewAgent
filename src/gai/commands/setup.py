"""Config and API-balance commands."""

from __future__ import annotations

import json
from typing import Optional

import typer

from gai.cli_common import (
    _TRACE_OPT_HELP,
    _print_error,
    _print_footer,
    _start_trace,
    app,
    console,
)
from gai.config import (
    CONFIG_FILE,
    ProfileInfo,
    Settings,
    format_profiles_overview,
    list_profiles,
    load_settings,
    profiles_summary,
    save_settings,
    settings_from_profile,
    settings_summary,
)
from gai.errors import format_cli_error
from gai.help_i18n import H
from gai.llm.balance import fetch_balance, format_balance_brief, format_balance_result
from gai.llm.client import LLMError


@app.command(
    "balance",
    help=H(
        "Show remaining API credit/balance when the provider supports it.",
        "查询 API Key 剩余额度（若当前厂商提供余额接口）。",
    ),
)
def balance_cmd(
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Use Simplified Chinese output.",
            "使用简体中文输出；与 -h 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """Query provider balance; requires a configured API key."""
    _start_trace(trace)
    try:
        settings = load_settings()
        status = (
            "正在查询余额..."
            if cn
            else "Checking balance..."
        )
        with console.status(f"[bold]{status}[/bold]"):
            result = fetch_balance(settings)
        text = format_balance_result(result, chinese=cn)
        style = "yellow" if not result.supported else "green"
        console.print(f"[{style}]{text}[/{style}]")
    except typer.Exit:
        raise
    except (LLMError, RuntimeError) as exc:
        _print_error(exc, chinese=cn, trace=trace)
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None
    finally:
        _print_footer(trace=trace, chinese=cn)


def _query_profile_balance(
    profile: ProfileInfo, *, chinese: bool, template: Settings
) -> str:
    """Best-effort one-line balance for one profile; never raises."""
    if not profile.api_key:
        return "未设置 API Key" if chinese else "API key not set"
    try:
        settings = settings_from_profile(profile, template)
        result = fetch_balance(settings)
        return format_balance_brief(result, chinese=chinese)
    except (LLMError, RuntimeError, OSError) as exc:
        msg = format_cli_error(exc, chinese=chinese)
        first = msg.splitlines()[0].strip() if msg else str(exc)
        return f"查询失败（{first}）" if chinese else f"lookup failed ({first})"
    except Exception as exc:  # noqa: BLE001 — list must still print
        return f"查询失败（{exc}）" if chinese else f"lookup failed ({exc})"


def _attach_profile_balances(
    rows: list[dict[str, str]], *, chinese: bool
) -> list[dict[str, str]]:
    """Add a balance field to each listed profile."""
    template = load_settings()
    profiles = list_profiles()
    by_name = {p.name: p for p in profiles}
    out: list[dict[str, str]] = []
    for row in rows:
        info = by_name.get(row.get("profile", ""))
        if info is None:
            info = ProfileInfo(name=row.get("profile", ""))
        balance = _query_profile_balance(info, chinese=chinese, template=template)
        out.append({**row, "balance": balance})
    return out


@app.command(
    "config",
    help=H(
        "View or update ~/.gai/config.toml.",
        "查看或更新 ~/.gai/config.toml。",
    ),
)
def config_cmd(
    show: bool = typer.Option(
        False,
        "--show",
        help=H(
            "Show current effective settings (secrets masked).",
            "显示当前生效配置（密钥已掩码）。",
        ),
    ),
    list_profiles_flag: bool = typer.Option(
        False,
        "--list",
        "-l",
        help=H(
            "List profiles, show the active number, and query each key's balance.",
            "列出配置档与当前编号，并为每个 API Key 查询余额（不支持则说明）。",
        ),
    ),
    use_profile: Optional[str] = typer.Option(
        None,
        "--use",
        help=H(
            "Switch active profile written to config (e.g. 0, 1, deepseek).",
            "切换并写入当前配置档（如 0、1、deepseek）。",
        ),
    ),
    profile_name: Optional[str] = typer.Option(
        None,
        "--name",
        help=H(
            "Target profile id when saving --api-key/--base-url/--model.",
            "与 --api-key/--base-url/--model 联用时写入指定配置档。",
        ),
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help=H("Set API key.", "设置 API Key。"),
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help=H(
            "Set OpenAI-compatible API base URL.",
            "设置 OpenAI 兼容 API Base URL。",
        ),
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help=H("Set model name.", "设置模型名。"),
    ),
    timeout: Optional[float] = typer.Option(
        None,
        "--timeout",
        help=H("HTTP timeout seconds.", "HTTP 超时秒数。"),
    ),
    max_diff_chars: Optional[int] = typer.Option(
        None,
        "--max-diff-chars",
        help=H(
            "Max staged-diff characters sent to the model.",
            "送入模型的文本最大字符数。",
        ),
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Show help in Simplified Chinese (use with -h/--help).",
            "与 -h/--help 联用时显示中文帮助。",
        ),
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        "-t",
        help=_TRACE_OPT_HELP,
    ),
) -> None:
    """View or update ~/.gai/config.toml."""
    _ = cn
    _start_trace(trace)
    try:
        updates = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
            "max_diff_chars": max_diff_chars,
        }
        has_updates = any(v is not None for v in updates.values())
        if use_profile is not None and not str(use_profile).strip():
            console.print(
                "[red]错误：--use 需要配置档名称。[/red]"
                if cn
                else "[red]Error: --use requires a profile name.[/red]"
            )
            raise typer.Exit(code=2)
        if profile_name is not None and not str(profile_name).strip():
            console.print(
                "[red]错误：--name 需要配置档名称。[/red]"
                if cn
                else "[red]Error: --name requires a profile name.[/red]"
            )
            raise typer.Exit(code=2)
        if profile_name and not has_updates and use_profile is None:
            console.print(
                "[red]错误：--name 需与 --api-key/--base-url/--model 等一起使用。[/red]"
                if cn
                else "[red]Error: --name must be used with --api-key/--base-url/--model.[/red]"
            )
            raise typer.Exit(code=2)

        if has_updates or use_profile is not None:
            path = save_settings(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_diff_chars=max_diff_chars,
                profile=profile_name.strip() if profile_name else None,
                set_current=use_profile.strip() if use_profile else None,
            )
            console.print(f"[green]Saved[/green] {path}")
            if use_profile is not None:
                console.print(
                    f"[green]当前配置档 → {use_profile.strip()}[/green]"
                    if cn
                    else f"[green]Active profile → {use_profile.strip()}[/green]"
                )

        if list_profiles_flag:
            rows = profiles_summary(chinese=cn)
            console.print(format_profiles_overview(chinese=cn))
            if not rows:
                console.print("（尚无配置档）" if cn else "(no profiles yet)")
            else:
                status = (
                    "正在查询各配置档余额..."
                    if cn
                    else "Checking balance for each profile..."
                )
                with console.status(f"[bold]{status}[/bold]"):
                    rows = _attach_profile_balances(rows, chinese=cn)
                console.print(json.dumps(rows, indent=2, ensure_ascii=False))
            # Avoid dumping --show by default when user only asked for --list.
            if not show and not has_updates and use_profile is None:
                return

        if show or (not list_profiles_flag and not has_updates and use_profile is None):
            settings = load_settings()
            summary = settings_summary(settings)
            console.print(json.dumps(summary, indent=2, ensure_ascii=False))
            if not CONFIG_FILE.is_file() and not settings.api_key and not list_profiles():
                tip = (
                    "\n[dim]提示：可通过 GAI_API_KEY（档 0）/ GAI_API_KEY1（档 1）… "
                    "或 `gai config --api-key <key>` 设置密钥；"
                    "`gai config --list` 查看全部配置档。[/dim]"
                    if cn
                    else "\n[dim]Tip: set GAI_API_KEY (profile 0) / GAI_API_KEY1 "
                    "(profile 1)… or `gai config --api-key <key>`; "
                    "`gai config --list` lists profiles.[/dim]"
                )
                console.print(tip)
    finally:
        _print_footer(trace=trace, chinese=cn)
