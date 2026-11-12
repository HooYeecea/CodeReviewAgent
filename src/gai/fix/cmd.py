"""Explicit, interactive repair entry points."""
import json

import typer

from gai.cli_common import app, console, _print_error
from gai.common.i18n import H
from gai.fix.engine import FixSession


def terminal(session):
    if not session.report:
        for report in session.catalog():
            console.print(f"{report['id']}  {report.get('title', '')}", markup=False)
        session.select(typer.prompt("报告 ID 或文件 / Report ID or path"))
    console.print(session.note, markup=False)
    if not session.findings:
        console.print("报告没有可修复的问题 / No findings to repair")
        return
    if not typer.confirm("调用模型验证当前代码中的问题？ / Verify current findings?", default=False):
        return
    session.validate()
    for issue in session.findings:
        console.print(f"{issue['id']}. [{issue['severity']}] {issue['file']}:{issue['line']}\n"
                      f"{issue['issue']}\n建议: {issue['suggestion']}\n"
                      f"{issue['status']}: {issue['reason']} {issue['blocked']}", markup=False)
    eligible = [i['id'] for i in session.findings if i['status'] == 'still_present' and not i['blocked']]
    if not eligible:
        console.print("没有已确认且可安全修复的问题 / No eligible findings")
        return
    choice = typer.prompt("选择编号（逗号分隔，all 全选，空输入取消） / Issue IDs", default="", show_default=False)
    if not choice.strip():
        return
    try:
        ids = eligible if choice.strip() == "all" else [int(n.strip()) for n in choice.split(',')]
    except ValueError:
        raise RuntimeError("请输入问题编号 / Enter numeric issue IDs") from None
    session.generate(ids)
    for file in session.proposal['public']['files']:
        console.print(file['diff'], markup=False, highlight=False)
    for issue in session.proposal['public']['unresolved']:
        console.print(f"未解决 {issue['id']}: {issue['reason']}", markup=False)
    if not typer.confirm("确认将以上补丁写入工作区？ / Apply this patch?", default=False):
        return
    session.apply(session.proposal['public']['ticket'])
    console.print(f"修复记录 / Repair record: {session.folder / 'session.json'}", markup=False)
    session.verify()
    console.print(json.dumps(session.verification, ensure_ascii=False, indent=2), markup=False)


def start_fix(*, selection=None, record=None, gui=False, open_browser=True):
    session = FixSession()
    if record is not None:
        session.use_record(record)
    elif selection:
        session.select(selection)
    if gui:
        from gai.fix.gui import serve_fix
        serve_fix(session, open_browser=open_browser)
    else:
        terminal(session)


@app.command("fix", help=H("Verify saved findings, preview and confirm repairs.", "验证历史审查问题，预览并确认修复。"))
def fix_cmd(
    report: str | None = typer.Argument(None, help=H("Local review ID or MD/JSON path.", "本仓库报告 ID 或 MD/JSON 路径。")),
    gui: bool = typer.Option(False, "--gui", help=H("Open the repair GUI.", "打开修复界面。")),
    no_open: bool = typer.Option(False, "--no-open", help=H("Print GUI URL without opening it.", "仅打印界面地址。")),
    cn: bool = typer.Option(False, "--cn", help=H("Chinese output/help.", "中文输出与帮助。")),
):
    try:
        if no_open and not gui:
            raise RuntimeError("--no-open 需要 --gui / --no-open requires --gui")
        start_fix(selection=report, gui=gui, open_browser=not no_open)
    except (RuntimeError, OSError, ValueError) as exc:
        _print_error(exc, chinese=cn, trace=False)
        raise typer.Exit(1) from exc
