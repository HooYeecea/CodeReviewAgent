"""gai CLI entrypoint."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from gai import __version__
from gai.config import CONFIG_FILE, load_settings, save_settings, settings_summary
from gai.git_ops import GitError, commit as git_commit, has_staged_changes, short_status
from gai.llm.client import LLMError
from gai.report import render_report, run_report
from gai.review import render_review, run_review

app = typer.Typer(
    name="gai",
    help="Local Git commit & code review agent.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gai {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """gai — AI-assisted local git commit & code review."""


@app.command("review")
def review_cmd(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print structured JSON (for editors / VS Code integration).",
    ),
    message_only: bool = typer.Option(
        False,
        "--message-only",
        help="Ask the model mainly for a commit message.",
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help="Output review findings and summary in Simplified Chinese.",
    ),
) -> None:
    """Review staged changes without committing."""
    try:
        if not has_staged_changes():
            err_console.print("[red]No staged changes. Run `git add` first.[/red]")
            raise typer.Exit(code=1)

        status_text = "正在调用大模型审查..." if cn else "Calling LLM for code review..."
        with console.status(f"[bold]{status_text}[/bold]"):
            result = run_review(
                message_only=message_only,
                review_only=not message_only,
                chinese=cn,
            )

        if as_json:
            console.print_json(data=result.to_dict())
            return

        render_review(result, console, chinese=cn)
        if result.commit_message:
            console.print()
            label = "建议的提交信息：" if cn else "Suggested commit message:"
            console.print(f"[bold]{label}[/bold] {result.commit_message}")
    except (GitError, LLMError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("commit")
def commit_cmd(
    message: Optional[str] = typer.Option(
        None,
        "--message",
        "-m",
        help="Use this commit message and skip AI message generation.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip interactive confirmation.",
    ),
    no_review: bool = typer.Option(
        False,
        "--no-review",
        help="Skip code review; only generate (or use) the commit message.",
    ),
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help="Skip all AI calls. Requires --message.",
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help="Output review findings and summary in Simplified Chinese.",
    ),
) -> None:
    """Review staged changes, suggest a commit message, then confirm and commit."""
    try:
        if not has_staged_changes():
            err_console.print("[red]No staged changes. Run `git add` first.[/red]")
            status = short_status()
            if status:
                err_console.print("[dim]Working tree:[/dim]")
                err_console.print(status)
            raise typer.Exit(code=1)

        if no_ai:
            if not message:
                err_console.print("[red]--no-ai requires --message / -m.[/red]")
                raise typer.Exit(code=1)
            final_message = message.strip()
            _confirm_and_commit(final_message, yes=yes, chinese=cn)
            return

        commit_message = (message or "").strip()
        result = None

        need_ai = (not commit_message) or (not no_review)
        if need_ai:
            status_text = "正在调用大模型..." if cn else "Calling LLM..."
            with console.status(f"[bold]{status_text}[/bold]"):
                result = run_review(
                    message_only=no_review and not commit_message,
                    review_only=not no_review and bool(commit_message),
                    chinese=cn,
                )

            if not no_review and result is not None:
                render_review(result, console, chinese=cn)
                console.print()

            if not commit_message and result is not None:
                if result.commit_message:
                    commit_message = result.commit_message
                elif not result.parsed_ok:
                    tip = (
                        "无法从模型输出中解析提交信息。"
                        if cn
                        else "Could not parse a commit message from the model."
                    )
                    err_console.print(f"[yellow]{tip}[/yellow]")

        if not commit_message:
            if yes:
                tip = (
                    "没有可用的提交信息，且已指定 --yes。"
                    if cn
                    else "No commit message available and --yes was set."
                )
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            prompt = "请输入提交信息" if cn else "Enter commit message"
            commit_message = Prompt.ask(prompt).strip()
            if not commit_message:
                tip = "提交信息为空，已取消。" if cn else "Empty commit message; aborted."
                err_console.print(f"[red]{tip}[/red]")
                raise typer.Exit(code=1)
            _confirm_and_commit(commit_message, yes=False, chinese=cn)
            return

        label = "建议的提交信息：" if cn else "Suggested commit message:"
        console.print(f"[bold]{label}[/bold] {commit_message}")
        if yes:
            _do_commit(commit_message, chinese=cn)
            return

        ask = "采纳该信息并提交？" if cn else "Adopt this message and commit?"
        if Confirm.ask(ask, default=True):
            _do_commit(commit_message, chinese=cn)
            return

        edit_ask = (
            "编辑提交信息（留空则取消）"
            if cn
            else "Edit message (leave empty to abort)"
        )
        edited = Prompt.ask(edit_ask, default="").strip()
        if not edited:
            console.print("已取消。" if cn else "Aborted.")
            raise typer.Exit(code=0)
        _do_commit(edited, chinese=cn)
    except (GitError, LLMError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        console.print("\n已取消。" if cn else "\nAborted.")
        raise typer.Exit(code=130) from None


def _confirm_and_commit(message: str, *, yes: bool, chinese: bool = False) -> None:
    label = "提交信息：" if chinese else "Commit message:"
    console.print(f"[bold]{label}[/bold] {message}")
    ask = "使用该信息提交？" if chinese else "Commit with this message?"
    if not yes and not Confirm.ask(ask, default=True):
        console.print("已取消。" if chinese else "Aborted.")
        raise typer.Exit(code=0)
    _do_commit(message, chinese=chinese)


def _do_commit(message: str, *, chinese: bool = False) -> None:
    git_commit(message)
    label = "已提交：" if chinese else "Committed:"
    console.print(f"[green]{label}[/green] {message}")


@app.command("report")
def report_cmd(
    since: str = typer.Option(
        "7d",
        "--since",
        "-s",
        help="Start of range: 7d / 2w / 2026-09-01 (default: 7d).",
    ),
    until: Optional[str] = typer.Option(
        None,
        "--until",
        "-u",
        help="End of range (YYYY-MM-DD or git-compatible date).",
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help="Filter by author. Use 'me' for current git user.",
    ),
    max_count: int = typer.Option(
        100,
        "--max-count",
        "-n",
        help="Max commits to include.",
    ),
    no_stat: bool = typer.Option(
        False,
        "--no-stat",
        help="Do not include git shortstat in the prompt.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print structured JSON.",
    ),
    cn: bool = typer.Option(
        False,
        "--cn",
        help="Write the work report in Simplified Chinese.",
    ),
) -> None:
    """Summarize git commits into a paste-ready work report."""
    try:
        status_text = "正在根据提交记录生成工作总结..." if cn else "Summarizing commits..."
        with console.status(f"[bold]{status_text}[/bold]"):
            result = run_report(
                since=since,
                until=until,
                author=author,
                max_count=max_count,
                include_stat=not no_stat,
                chinese=cn,
            )

        if as_json:
            console.print_json(data=result.to_dict())
            return

        render_report(result, console, chinese=cn)
    except (GitError, LLMError, RuntimeError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("config")
def config_cmd(
    show: bool = typer.Option(
        False,
        "--show",
        help="Show current effective settings (secrets masked).",
    ),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Set API key."),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Set OpenAI-compatible API base URL.",
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Set model name."),
    timeout: Optional[float] = typer.Option(None, "--timeout", help="HTTP timeout seconds."),
    max_diff_chars: Optional[int] = typer.Option(
        None,
        "--max-diff-chars",
        help="Max staged-diff characters sent to the model.",
    ),
) -> None:
    """View or update ~/.gai/config.toml."""
    updates = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": timeout,
        "max_diff_chars": max_diff_chars,
    }
    if any(v is not None for v in updates.values()):
        path = save_settings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_diff_chars=max_diff_chars,
        )
        console.print(f"[green]Saved[/green] {path}")

    if show or all(v is None for v in updates.values()):
        settings = load_settings()
        summary = settings_summary(settings)
        console.print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not CONFIG_FILE.is_file() and not settings.api_key:
            console.print(
                "\n[dim]Tip: set key via env GAI_API_KEY / OPENAI_API_KEY "
                "or `gai config --api-key <key>`.[/dim]"
            )


if __name__ == "__main__":
    app()
    sys.exit(0)
