"""Visual guide content, backed by the actual registered CLI command tree."""
from __future__ import annotations

import ast
from pathlib import Path

from gai.cli_usage import command_examples


GROUPS = [
    {"id": "workflow", "cn": "审查与工作流", "en": "Review & workflows"},
    {"id": "workspace", "cn": "工作区与暂存", "en": "Workspace & staging"},
    {"id": "branches", "cn": "分支与整合", "en": "Branches & integration"},
    {"id": "sync", "cn": "远程同步", "en": "Remote sync"},
    {"id": "insight", "cn": "历史与报告", "en": "History & reports"},
    {"id": "setup", "cn": "配置与工具", "en": "Configuration & tools"},
]
MEMBERS = {
    "workflow": "review commit devflow splitflow flow",
    "workspace": "add unadd uncommit status",
    "branches": "branch switch merge rebase stash",
    "sync": "push pull",
    "insight": "log graph report usage history",
    "setup": "balance config completion guide",
}


def pair(cn, en):
    return {"cn": cn, "en": en}


# Steps describe the default path; flags and recovery branches are shown separately.
STEPS = {
    "splitflow": [
        ("拆分计划", "Plan", "将未提交改动按主题分组，并选择提交词语言。", "Group uncommitted changes and choose commit message language."),
        ("暂存批次", "Stage", "只暂存当前批次的文件。", "Stage the files in the current batch."),
        ("审查代码", "Review", "审查暂存内容；过大批次最多再拆分一级。", "Review the staged diff; oversized batches can split one level further."),
        ("创建提交", "Commit", "按所选语言生成提交词，提交本批次，再处理下一批。", "Commit in the chosen language, then continue to the next batch."),
        ("核实推送", "Push", "全部批次完成后推送；--no-push 可在本地结束。", "Push after all batches; --no-push finishes locally."),
    ],
    "devflow": [
        ("选择文件", "Select", "采纳 AI 暂存建议，或自行选择路径。", "Accept AI staging suggestions or choose paths yourself."),
        ("审查", "Review", "审查已暂存代码；需要时切换 splitflow。", "Review staged code; switch to splitflow when needed."),
        ("选择提交词", "Message", "选择中文、英文或手动输入提交信息。", "Choose Chinese, English or a custom commit message."),
        ("提交与推送", "Commit & push", "确认提交，再决定是否推送。", "Confirm the commit, then decide whether to push."),
    ],
    "review": [("准备暂存区", "Stage first", "先用 gai add 暂存需要审查的代码。", "Stage the code with gai add first."), ("AI 审查", "AI review", "读取暂存差异，生成问题与摘要。", "Inspect the staged diff and produce findings and a summary."), ("阅读与修复", "Read & fix", "此命令不创建提交；修复后重新暂存、审查。", "No commit is created; restage and review after fixes.")],
    "commit": [("已有暂存", "Staged changes", "先暂存待提交的改动。", "Stage changes before committing."), ("审查与提交词", "Review & message", "默认调用 AI 审查并生成提交信息。", "By default, AI reviews the diff and suggests a message."), ("确认提交", "Confirm commit", "确认后创建本地提交；--push 可随后推送。", "Confirm to create a local commit; --push can push afterward.")],
    "add": [("工作区改动", "Working files", "选择文件路径；不指定路径时默认为当前目录。", "Choose paths; omitting paths uses the current directory."), ("加入暂存区", "Stage", "将所选内容加入暂存区。", "Add selected contents to the index."), ("下一步", "Next", "使用 review 审查，或 commit 进入提交流程。", "Use review to inspect changes, or commit to start a commit flow.")],
    "push": [("本地提交", "Local commits", "准备本地提交与已配置的远程。", "Have local commits and a configured remote."), ("检查远程", "Check remote", "获取远程信息，检查是否有待推送提交。", "Fetch remote state and check for outgoing commits."), ("确认推送", "Confirm push", "确认后推送；不会自动强制覆盖远程。", "Confirm to push; remote history is not force-overwritten.")],
    "pull": [("检查远程", "Check remote", "获取远程信息，检查落后提交数。", "Fetch remote state and check incoming commits."), ("选择整合方式", "Choose strategy", "根据情况选择 merge 或 rebase；有本地改动时需额外处理。", "Choose merge or rebase as needed; local edits require attention."), ("整合或处理冲突", "Integrate", "整合远程提交；冲突时按提示处理。", "Integrate remote commits and resolve conflicts if needed.")],
    "flow status": [("读取检查点", "Read checkpoint", "查看阶段、已完成批次和最近错误。", "See the phase, completed batches and latest failure."), ("恢复预检", "Preflight", "--check 核对当前 Git 状态，不执行暂存、提交或推送。", "--check verifies Git state without staging, committing or pushing."), ("选择恢复方式", "Choose recovery", "按情况继续、重审当前批次或重规划剩余改动。", "Resume, review the current batch or replan remaining changes.")],
    "flow abort": [("找到未完成流程", "Find session", "定位当前工作区的流程记录。", "Locate the unfinished session in this worktree."), ("确认放弃记录", "Confirm discard", "放弃恢复记录，不回滚文件、暂存区或已有提交。", "Discard the session without reverting files, the index or existing commits."), ("重新开始", "Start again", "检查现有改动后，可以启动新流程。", "Inspect current changes, then start a new flow.")],
}

EXTRA_EXAMPLES = {
    "splitflow": [
        ("gai splitflow --cn --yes", "只选提交词语言，自动确认到推送", "Choose message language; auto-confirm through push"),
        ("gai splitflow --cn --yes --no-push", "自动处理批次，仅保留本地提交", "Process batches automatically, finishing locally"),
        ("gai splitflow --resume --cn", "继续已保存的流程", "Continue the saved session"),
        ("gai splitflow --resume --review-current --cn", "修复当前批次后重新审查", "Review the current batch after fixes"),
        ("gai splitflow --resume --replan --cn", "保留已完成提交，重规划剩余改动", "Keep completed commits and replan remaining changes"),
        ("gai splitflow --resume --interactive --cn", "恢复人工确认", "Restore interactive confirmations"),
    ],
    "devflow": [("gai devflow --resume --cn", "恢复未完成流程", "Resume an unfinished flow")],
    "flow status": [("gai flow status --check --cn", "预检恢复条件", "Check whether recovery can proceed"), ("gai flow status --cn", "查看进度和最近错误", "Inspect progress and the latest failure")],
    "flow abort": [("gai flow abort --cn", "放弃流程记录，保留代码与提交", "Discard the session; keep files and commits")],
    "completion install": [("gai completion install --shell powershell --cn", "安装 PowerShell 补全后重新打开终端", "Install PowerShell completion, then reopen the terminal")],
    "completion show": [("gai completion show --shell powershell", "查看 PowerShell 补全脚本", "Show the PowerShell completion script")],
}

# Short operation maps complement the full CLI help shown in the parameter panel.
STEPS.update({
    "unadd": [
        ("选择范围", "Choose paths", "指定路径；省略路径时撤销全部暂存。", "Specify paths, or omit them to unstage everything."),
        ("确认撤销暂存", "Confirm", "确认后将所选改动移出暂存区。", "Confirm to remove selected changes from the index."),
        ("保留工作区", "Keep edits", "文件改动仍保留，可调整后重新 add。", "File edits remain; adjust them and stage again when ready."),
    ],
    "uncommit": [
        ("检查最近提交", "Inspect HEAD", "确认最近一次提交正是需要撤销的提交。", "Check that the latest commit is the one to undo."),
        ("确认软撤销", "Confirm soft reset", "确认后撤销最近一次本地提交。", "Confirm to undo the latest local commit."),
        ("重新提交", "Recommit", "改动保留在暂存区，可修改提交信息后重新提交。", "Changes stay staged so you can commit again with a new message."),
    ],
    "status": [
        ("进入仓库", "Open repository", "在需要检查的 Git 仓库中运行。", "Run inside the Git repository you want to inspect."),
        ("查看状态", "Read status", "区分已暂存、未暂存和未跟踪文件。", "Distinguish staged, unstaged and untracked files."),
        ("选择下一步", "Choose next action", "按需暂存、审查或处理现有改动。", "Stage, review or handle existing changes as needed."),
    ],
    "branch": [
        ("命名分支", "Name branch", "提供新分支名；可指定起点。", "Provide a new branch name and optionally a starting point."),
        ("确认创建", "Confirm creation", "核对起点与分支名后确认。", "Check the starting point and branch name, then confirm."),
        ("切换工作", "Switch work", "按需要使用 gai switch 切换到目标分支。", "Use gai switch to switch to the desired branch when needed."),
    ],
    "switch": [
        ("选择分支", "Choose branch", "提供目标分支名，检查当前本地改动。", "Provide the target branch and inspect local edits."),
        ("确认切换", "Confirm switch", "确认后切换；存在阻碍时按提示处理。", "Confirm the switch; follow prompts if it is blocked."),
        ("检查状态", "Verify status", "用 gai status 查看当前工作区。", "Use gai status to inspect the resulting working tree."),
    ],
    "merge": [
        ("选定来源", "Choose source", "在目标分支上指定要合入的分支。", "On the destination branch, name the branch to merge."),
        ("确认合并", "Confirm merge", "核对合并内容，再执行 merge。", "Review the merge and confirm it."),
        ("解决冲突", "Resolve conflicts", "有冲突时修复并暂存，再用 --continue；放弃则用 --abort。", "Fix and stage conflicts, then use --continue; use --abort to abandon the merge."),
    ],
    "rebase": [
        ("选择上游", "Choose upstream", "指定当前分支要变基到的目标。", "Specify the upstream for the current branch."),
        ("确认变基", "Confirm rebase", "确认后在目标之上重放提交，提交哈希可能改变。", "Replay commits onto the target; commit hashes may change."),
        ("解决冲突", "Resolve conflicts", "修复并暂存后 --continue；需要取消则 --abort。", "Fix and stage conflicts, then --continue; use --abort to cancel."),
    ],
    "stash": [
        ("选择存入或弹出", "Save or restore", "默认存入当前改动；--pop 弹出最近一条。", "Save current edits by default; --pop restores the latest entry."),
        ("确认操作", "Confirm action", "核对改动或 stash 条目后确认。", "Check the edits or stash entry and confirm."),
        ("检查工作区", "Inspect files", "存入后可切换任务；弹出后检查改动及冲突。", "Switch tasks after saving; inspect edits and conflicts after restoring."),
    ],
    "log": [
        ("选择范围", "Choose range", "使用参数限定要查看的提交历史。", "Use options to narrow the commit history."),
        ("阅读提交", "Read commits", "查看提交信息、作者和时间。", "Inspect messages, authors and timestamps."),
        ("继续查看", "Explore", "需要分支图时使用 gai graph。", "Use gai graph when you need a branch diagram."),
    ],
    "graph": [
        ("选择范围", "Choose range", "选择分支、数量等图形参数。", "Choose branch, count and other graph options."),
        ("生成提交图", "Build graph", "根据 Git 历史绘制提交及分支关系。", "Draw commits and branch relationships from Git history."),
        ("浏览节点", "Explore nodes", "在图中查看提交与合并关系。", "Explore commits and merges in the graph."),
    ],
    "report": [
        ("指定范围", "Choose scope", "按下方参数选择统计范围。", "Choose the reporting scope using the options below."),
        ("生成工作报告", "Build report", "汇总范围内的 Git 提交。", "Summarize Git commits within the selected scope."),
        ("阅读或导出", "Read or export", "阅读终端中的工作总结，或按参数导出报告。", "Read the work summary in the terminal, or export it using the available options."),
    ],
    "usage": [
        ("筛选用量", "Filter usage", "按时间、模型或厂商等参数筛选。", "Filter by time, model, provider or other options."),
        ("查看统计", "Inspect totals", "默认终端查看当前仓库用量。", "The terminal shows usage for the current repository by default."),
        ("打开全局报告", "Open dashboard", "--report 或 --serve 生成全局用量报告。", "Use --report or --serve for the global usage dashboard."),
    ],
    "history": [
        ("筛选记录", "Filter history", "按下方参数选择命令执行记录。", "Select command execution records using the options below."),
        ("查看本地历史", "Read local history", "默认显示当前仓库的 gai 命令记录。", "Show gai command history for the current repository by default."),
        ("浏览全局历史", "Explore globally", "--report 或 --serve 查看跨仓库的命令记录。", "Use --report or --serve for history across repositories."),
    ],
    "config": [
        ("查看配置", "Inspect settings", "用 --show 查看当前配置，--list 查看配置列表。", "Use --show for current settings and --list for available profiles."),
        ("设置服务", "Set provider", "根据服务填写 API 地址、模型名与密钥。", "Set the API URL, model and key for your provider."),
        ("选择配置", "Select profile", "用 --use 切换配置，再执行需要 AI 的命令。", "Switch profiles with --use, then run commands that need AI."),
    ],
    "balance": [
        ("准备配置", "Configure provider", "先配置服务商及有效密钥。", "Configure a provider and a valid API key first."),
        ("查询余额", "Query balance", "请求当前服务商提供的余额信息。", "Request balance information from the configured provider."),
        ("查看结果", "Read result", "查看余额；服务商不支持时按提示处理。", "Read the balance or the notice if the provider does not support it."),
    ],
    "guide": [
        ("生成指南", "Generate guide", "运行 gai guide，将指南写入 .gai/guide.html。", "Run gai guide to write .gai/guide.html."),
        ("打开页面", "Open page", "使用 --open 或 --serve 打开页面。", "Use --open or --serve to open the page."),
        ("切换视图", "Choose view", "在文字指南和图形化指南之间切换。", "Switch between the text and visual guides."),
    ],
    "completion install": [
        ("选择终端", "Choose shell", "自动检测终端，或用 --shell 指定。", "Detect the shell automatically, or specify --shell."),
        ("安装补全", "Install", "将补全脚本写入对应终端的配置。", "Install the completion script for the selected shell."),
        ("重新打开终端", "Reopen terminal", "重新打开终端后输入 gai 并按 Tab。", "Reopen your terminal, type gai and press Tab."),
    ],
    "completion show": [
        ("选择终端", "Choose shell", "用 --shell 选择补全脚本的类型。", "Select a completion script type with --shell."),
        ("打印脚本", "Print script", "输出脚本内容，便于检查。", "Print the script so you can inspect it."),
        ("按需安装", "Install if needed", "需要自动安装时使用 gai completion install。", "Use gai completion install for automatic installation."),
    ],
})


def _help_translations():
    """Read literal H(en, cn) definitions, without running commands or reading config."""
    pairs = {}
    for path in Path(__file__).resolve().parents[1].rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "H" and len(node.args) >= 2):
                try:
                    en, cn = (ast.literal_eval(arg) for arg in node.args[:2])
                except (ValueError, TypeError):
                    continue
                if isinstance(en, str) and isinstance(cn, str):
                    pairs[en] = pairs[cn] = pair(cn, en)
    return pairs


def command_catalog(existing):
    # Import lazily: page generation happens after CLI registration is complete.
    from gai.cli import app
    from typer.main import get_command
    root = get_command(app)
    known = {item["id"]: item for item in existing}
    translations = _help_translations()
    commands = []
    titles = {
        "flow": pair("流程恢复", "Flow recovery"),
        "flow status": pair("检查恢复状态", "Inspect recovery"),
        "flow abort": pair("放弃流程记录", "Discard session"),
        "completion install": pair("安装补全", "Install completion"),
        "completion show": pair("查看补全脚本", "Show completion script"),
    }
    descriptions = {
        "flow status": pair("查看保存的进度、批次和最近错误；用 --check 预检恢复条件。", "Inspect saved progress, batches and the latest failure; use --check to preview recovery."),
        "flow abort": pair("确认后放弃流程记录；保留工作区文件、暂存内容和已有提交。", "Confirm to discard the saved session while keeping files, staged changes and existing commits."),
    }

    def visit(command, path, parent=None):
        key = " ".join(path)
        children = {name: child for name, child in getattr(command, "commands", {}).items()
                    if not getattr(child, "hidden", False)}
        meta = known.get(key)
        description = translations.get(str(command.help), pair(str(command.help or ""), str(command.help or "")))
        description = descriptions.get(key, description)
        if key:
            category = next((group for group, names in MEMBERS.items() if path[0] in names.split()), "setup")
            options, arguments = [], []
            for parameter in command.params:
                if getattr(parameter, "hidden", False):
                    continue
                option = getattr(parameter, "param_type_name", "") == "option"
                flags = list(getattr(parameter, "opts", [])) + list(getattr(parameter, "secondary_opts", []))
                help_text = str(getattr(parameter, "help", "") or "")
                help_pair = translations.get(help_text, pair(help_text, help_text))
                if not help_text and parameter.name == "cn":
                    help_pair = pair("使用中文提示。", "Use Chinese messages.")
                row = {"name": parameter.name, "flags": flags, "required": bool(parameter.required),
                       "flag": bool(getattr(parameter, "is_flag", False)), "type": str(parameter.type),
                       "help": help_pair}
                (options if option else arguments).append(row)
            examples = [(line, cn, en) for line, en, cn in command_examples(key)]
            examples.extend(EXTRA_EXAMPLES.get(key, []))
            examples.append((f"gai {key} --help", "查看此命令的完整帮助", "Read the complete command help"))
            unique_examples = {}
            for line, cn, en in examples:
                unique_examples.setdefault(line, dict(command=line, description=pair(cn, en)))
            examples = list(unique_examples.values())
            steps = STEPS.get(key)
            if steps is None:
                if children:
                    steps = [("选择子命令", "Choose a subcommand", "从下方层级中选择要完成的操作。", "Choose an action from the child commands below."),
                             ("查看用法", "Inspect usage", "查看对应流程、参数和示例。", "Inspect its flow, parameters and examples.")]
                else:
                    steps = [("准备输入", "Prepare", "按下方参数说明准备路径、分支或选项。", "Prepare paths, branches or options listed below."),
                             ("运行命令", "Run", description["cn"], description["en"]),
                             ("查看结果", "Inspect", "阅读终端输出；需要下一步操作时遵循命令提示。", "Read the terminal output and follow any next-step prompts.")]
            commands.append({"id": key, "parent": parent, "group": category, "children": [f"{key} {n}" for n in children],
                "title": pair(meta["cn"]["title"], meta["en"]["title"]) if meta else titles.get(key, description),
                "description": pair(meta["cn"]["blurb"], meta["en"]["blurb"]) if meta else description,
                "options": options, "arguments": arguments, "examples": examples,
                "steps": [{"title": pair(cn, en), "body": pair(body_cn, body_en)} for cn, en, body_cn, body_en in steps]})
        for name, child in children.items():
            if not getattr(child, "hidden", False):
                visit(child, [*path, name], key or None)
    visit(root, [])
    return {"groups": GROUPS, "commands": commands}
