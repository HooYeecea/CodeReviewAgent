"""Shell Tab-completion helpers for the gai CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from gai.help_i18n import H

# Supported by Typer / Click shell completion
SHELL_CHOICES = ("bash", "zsh", "fish", "powershell", "pwsh")

completion_app = typer.Typer(
    name="completion",
    help=H(
        "Install or show shell Tab-completion for gai.",
        "安装或查看 gai 的 shell Tab 自动补全。",
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_console = Console()
_err = Console(stderr=True)


@completion_app.callback()
def _completion_root(
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H(
            "Show help in Simplified Chinese (use with -h/--help).",
            "与 -h/--help 联用时显示中文帮助。",
        ),
        is_eager=True,
    ),
) -> None:
    _ = cn


def _resolve_shell(shell: Optional[str], *, chinese: bool = False) -> str:
    from typer._completion_shared import _get_shell_name

    name = (shell or _get_shell_name() or "").strip().lower()
    if name not in SHELL_CHOICES:
        supported = ", ".join(SHELL_CHOICES)
        if chinese:
            _err.print(
                f"[red]无法识别 shell：{name or '（未检测到）'}。"
                f"请用 --shell 指定：{supported}[/red]"
            )
        else:
            _err.print(
                f"[red]Unsupported or undetected shell: {name or '(none)'}. "
                f"Pass --shell {{{supported}}}[/red]"
            )
        raise typer.Exit(code=2)
    return name


@completion_app.command(
    "install",
    help=H(
        "Install Tab-completion into the current (or specified) shell profile.",
        "把 Tab 补全写入当前（或指定）shell 的配置文件。",
    ),
)
def completion_install(
    shell: Optional[str] = typer.Option(
        None,
        "--shell",
        "-s",
        help=H(
            "Shell: bash / zsh / fish / powershell / pwsh. Default: auto-detect.",
            "指定 shell：bash / zsh / fish / powershell / pwsh。默认自动检测。",
        ),
        case_sensitive=False,
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H("Chinese messages.", "中文提示。"),
    ),
) -> None:
    from typer.completion import install as install_completion

    resolved = _resolve_shell(shell, chinese=cn)
    shell_name, path = install_completion(shell=resolved, prog_name="gai")
    if cn:
        _console.print(
            f"[green]已为 {shell_name} 安装补全：[/green]{path}\n"
            "[dim]请重新打开终端后生效。试用：输入 `gai ` 或 `gai r` 后按 Tab。[/dim]"
        )
    else:
        _console.print(
            f"[green]{shell_name} completion installed in[/green] {path}\n"
            "[dim]Restart the terminal, then try: `gai ` or `gai r` + Tab.[/dim]"
        )


@completion_app.command(
    "show",
    help=H(
        "Print the completion script (for manual install or inspection).",
        "打印补全脚本（便于手动安装或检查）。",
    ),
)
def completion_show(
    shell: Optional[str] = typer.Option(
        None,
        "--shell",
        "-s",
        help=H(
            "Shell: bash / zsh / fish / powershell / pwsh. Default: auto-detect.",
            "指定 shell：bash / zsh / fish / powershell / pwsh。默认自动检测。",
        ),
        case_sensitive=False,
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help=H("Chinese messages (stderr tip only).", "中文提示（仅 stderr 提示）。"),
    ),
) -> None:
    from typer.completion import get_completion_script

    resolved = _resolve_shell(shell, chinese=cn)
    script = get_completion_script(
        prog_name="gai",
        complete_var="_GAI_COMPLETE",
        shell=resolved,
    )
    # Script must go to stdout alone so users can redirect it.
    typer.echo(script)
    if cn:
        _err.print(
            f"[dim]以上为 {resolved} 补全脚本。"
            "PowerShell 可追加到 $PROFILE；bash/zsh 可 source 到 rc 文件。[/dim]"
        )
    else:
        _err.print(
            f"[dim]Above: {resolved} completion script. "
            "Append to $PROFILE (PowerShell) or source from your shell rc.[/dim]"
        )
