"""Shell Tab-completion helpers for the gai CLI."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from gai.help_i18n import H

# Supported by Typer / Click shell completion
SHELL_CHOICES = ("bash", "zsh", "fish", "powershell", "pwsh")

COMPLETE_VAR = "_GAI_COMPLETE"
PROG_NAME = "gai"

# Markers so re-install replaces the previous block instead of appending forever.
_PS_BEGIN = "# >>> gai completion >>>"
_PS_END = "# <<< gai completion <<<"

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


def powershell_completion_script(*, prog_name: str = PROG_NAME, complete_var: str = COMPLETE_VAR) -> str:
    """PowerShell completer with try/finally so env vars cannot stick after Tab."""
    # Avoid Set-PSReadLineKeyHandler here: remapping Tab globally surprises users.
    # MenuComplete can be enabled by the user if they want a completion menu.
    return f"""{_PS_BEGIN}
$scriptblock = {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $Env:{complete_var} = "complete_powershell"
    $Env:_TYPER_COMPLETE_ARGS = $commandAst.ToString()
    $Env:_TYPER_COMPLETE_WORD_TO_COMPLETE = $wordToComplete
    try {{
        & {prog_name} 2>$null | ForEach-Object {{
            $commandArray = $_ -Split ":::"
            $command = $commandArray[0]
            $helpString = if ($commandArray.Count -gt 1) {{ $commandArray[1] }} else {{ " " }}
            if (-not [string]::IsNullOrWhiteSpace($command)) {{
                [System.Management.Automation.CompletionResult]::new(
                    $command, $command, 'ParameterValue', $helpString)
            }}
        }}
    }} finally {{
        Remove-Item Env:{complete_var} -ErrorAction SilentlyContinue
        Remove-Item Env:_TYPER_COMPLETE_ARGS -ErrorAction SilentlyContinue
        Remove-Item Env:_TYPER_COMPLETE_WORD_TO_COMPLETE -ErrorAction SilentlyContinue
    }}
}}
Register-ArgumentCompleter -Native -CommandName {prog_name} -ScriptBlock $scriptblock
{_PS_END}
"""


def _powershell_profile_path(shell: str) -> Path:
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", "echo", "$profile"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise RuntimeError(f"could not resolve ${shell} $PROFILE")
    return Path(text)


_LEGACY_PS_BLOCK = re.compile(
    r"(?ms)"
    r"Import-Module PSReadLine\s*"
    r"Set-PSReadLineKeyHandler -Chord Tab -Function MenuComplete\s*"
    r"\$scriptblock = \{.*?\}\s*"
    r"Register-ArgumentCompleter -Native -CommandName gai -ScriptBlock \$scriptblock\s*"
)

_MARKED_PS_BLOCK = re.compile(
    rf"(?ms){re.escape(_PS_BEGIN)}.*?{re.escape(_PS_END)}\s*"
)


def install_powershell_completion(*, shell: str) -> Path:
    """Install/replace gai completion block in the PowerShell profile."""
    path = _powershell_profile_path(shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    # Drop prior gai completer (marked or Typer's original append).
    cleaned = _MARKED_PS_BLOCK.sub("", existing)
    cleaned = _LEGACY_PS_BLOCK.sub("", cleaned)
    cleaned = cleaned.rstrip() + ("\n\n" if cleaned.strip() else "")
    cleaned += powershell_completion_script() + "\n"
    path.write_text(cleaned, encoding="utf-8")
    return path


def get_shell_completion_script(*, shell: str) -> str:
    if shell in {"powershell", "pwsh"}:
        return powershell_completion_script().strip()
    from typer.completion import get_completion_script

    return get_completion_script(
        prog_name=PROG_NAME,
        complete_var=COMPLETE_VAR,
        shell=shell,
    )


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
    resolved = _resolve_shell(shell, chinese=cn)
    if resolved in {"powershell", "pwsh"}:
        path = install_powershell_completion(shell=resolved)
        shell_name = resolved
    else:
        from typer.completion import install as install_completion

        shell_name, path = install_completion(shell=resolved, prog_name=PROG_NAME)

    if cn:
        _console.print(
            f"[green]已为 {shell_name} 安装补全：[/green]{path}\n"
            "[dim]请重新打开终端后生效。试用：输入 `gai ` 或 `gai r` 后按 Tab。[/dim]\n"
            "[yellow]若当前窗口里 `gai -h` 只显示 `--cn:::` 这类内容，先执行：[/yellow]\n"
            "  Remove-Item Env:_GAI_COMPLETE, Env:_TYPER_COMPLETE_ARGS, "
            "Env:_TYPER_COMPLETE_WORD_TO_COMPLETE -ErrorAction SilentlyContinue"
        )
    else:
        _console.print(
            f"[green]{shell_name} completion installed in[/green] {path}\n"
            "[dim]Restart the terminal, then try: `gai ` or `gai r` + Tab.[/dim]\n"
            "[yellow]If `gai -h` prints `--cn:::` lines, clear sticky env first:[/yellow]\n"
            "  Remove-Item Env:_GAI_COMPLETE, Env:_TYPER_COMPLETE_ARGS, "
            "Env:_TYPER_COMPLETE_WORD_TO_COMPLETE -ErrorAction SilentlyContinue"
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
    resolved = _resolve_shell(shell, chinese=cn)
    script = get_shell_completion_script(shell=resolved)
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
