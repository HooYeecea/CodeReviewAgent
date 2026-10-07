# gai — Local Git Commit & Code Review Agent

本地 CLI：对 **staged** 变更做 AI Code Review、生成 Conventional Commits 提交信息；可推送 / 拉取远程；可根据提交记录生成**工作总结**（周报 / 日报）。

要求 **Python 3.11+**，必须在 **git 仓库**目录下使用。

## 安装

```bash
cd CodeReviewAgent
python -m pip install -e ".[dev]"
```

验证：

```bash
gai --help
gai -h                 # 与 --help 相同
gai -h --cn            # 中文帮助
gai --version
gai commit -h --cn
gai report -h --cn
gai push -h --cn
gai pull -h --cn
gai balance -h --cn
gai config -h --cn
```

- 所有命令支持 `-h` / `--help`
- 与 `--cn` 联用时，帮助为简体中文
- 子命令上的 `--cn` 同时控制运行时文案（审查 / 报告 / 推送 / 拉取 / 错误提示等）

安装后会在当前 Python 的 `Scripts` 目录生成 `gai` 启动器。该目录在 PATH 中即可在任意 git 仓库使用（不必每个项目再装一次）。

### Tab 自动补全（推荐）

安装一次后，在终端里输入 `gai ` / `gai r` 再按 **Tab**，可补全或轮询子命令与选项。

PowerShell：

```powershell
gai completion install --shell powershell --cn
# 或：gai --install-completion
```

然后**重新打开**终端。试用：

```powershell
gai <Tab>          # 列出 / 轮询子命令
gai r<Tab>         # 补全为 review / report 等
gai commit --<Tab> # 补全选项
```

bash / zsh / fish：

```bash
gai completion install --cn
# 或指定：gai completion install --shell zsh --cn
```

查看脚本（不写入配置）：`gai completion show --shell powershell`

若误按 Tab 后 `gai -h` 只打印 `--cn:::` 这类行，说明补全环境变量残留，在当前窗口执行：

```powershell
Remove-Item Env:_GAI_COMPLETE, Env:_TYPER_COMPLETE_ARGS, Env:_TYPER_COMPLETE_WORD_TO_COMPLETE -ErrorAction SilentlyContinue
```

然后重开终端（或再执行一次 `gai completion install --shell powershell --cn` 以更新为带 try/finally 的脚本）。

## 配置

支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义兼容模式 / 硅基流动等）。

**优先级：环境变量 > `~/.gai/config.toml` > 默认值**

### 环境变量（推荐）

| 变量 | 含义 | 默认 |
|------|------|------|
| `GAI_API_KEY` 或 `OPENAI_API_KEY` | API Key | （调用大模型时必填） |
| `GAI_BASE_URL` 或 `OPENAI_BASE_URL` | API Base URL | `https://api.openai.com/v1` |
| `GAI_MODEL` | 模型名 | `gpt-4o-mini` |
| `GAI_TIMEOUT` | 请求超时（秒） | `60` |
| `GAI_MAX_DIFF_CHARS` | 送入模型的文本最大字符数 | `80000` |

Windows：在「系统属性 → 环境变量 → 用户变量」中设置。修改后需**重新打开**终端 / IDE。

PowerShell 临时设置（仅当前窗口）：

```powershell
$env:GAI_API_KEY = "sk-xxx"
$env:GAI_BASE_URL = "https://api.deepseek.com/v1"
$env:GAI_MODEL = "deepseek-chat"
```

### 配置文件

```bash
gai config --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
gai config --show --cn
```

写入：`~/.gai/config.toml`。

## 日常用法

```bash
gai add                   # git add .（也可 gai add src/）
gai review --cn           # 只审查，不提交
gai commit --cn           # 审查 → 建议 Message → 确认 → 提交
gai commit --cn --push    # 提交成功后推送到已配置 remote
gai push --cn             # 仅推送（无可推送时提示，不当成成功）
gai pull --cn             # 检查后确认再拉取
gai pull --rebase --cn    # 用 rebase 拉取
gai unadd --cn            # 撤销暂存（需确认）
gai uncommit --cn         # 撤销最近一次提交（soft，需确认）
gai report --cn           # 最近 7 天工作总结
gai balance --cn          # 查询 API Key 剩余额度（若厂商支持）
gai usage --cn            # 查看本地记录的 token 用量历史
gai history --cn          # 查看本地 gai 命令执行记录
gai history --serve --cn  # 同步命令执行报告并以本地 HTTP 打开
gai guide --cn --open     # 生成 .gai/guide.html 并用浏览器打开
gai usage --serve --cn    # 同步用量报告并以本地 HTTP 打开（刷新更稳）
gai devflow --cn          # 引导式：AI 暂存建议 → 审查 → 中英提交词 → 推送
gai add --cn -t           # 暂存并打印底层 git 链路
```

每个命令结束都会用**黄色**提示：本次是否调用了大模型；若调用则显示模型名与接口返回的 token。有确认步骤的命令（如 `commit` / `push` / `pull`）在**确认结束之后**再显示。

需要看底层 git 时加 `--trace` / `-t`。若本次没跑 git，会提示「本次未涉及 git 操作」。

### 工作总结

```bash
gai report --cn                              # 默认最近 7 天（团队总览，含参与者）
gai report --cn --per                        # 团队总览 + 按人明细
gai report --since 14d --cn
gai report --author me --cn                  # 当前 git 用户
gai report --since 2026-09-01 --until 2026-09-23 --author me --cn
gai report --alltime --cn
gai report --cn -o                           # 导出当前目录 gai-report-日期.md
gai report --cn --per -o 周报.md
gai report --cn -o .\reports\                # 目录不存在则自动创建
```

`--author me` 按本仓库 `git config user.email`（否则 `user.name`）过滤。未指定 `--author` 为团队报告；加 `--per` 再按人展开。

`--since` 支持 `7d` / `2w` / `1m` / `1y`、`YYYY-MM-DD`、`alltime`。`--alltime` 与 `--since alltime` 等价。`--since` 不得晚于 `--until`，非法日期会报错并给出正确格式示例。

## 命令一览

| 命令 | 作用 |
|------|------|
| `gai add` | 暂存（默认 `.`） |
| `gai unadd` | 撤销暂存（需确认） |
| `gai uncommit` | 软撤销最近一次提交（需确认） |
| `gai review` | 审查已暂存变更，不提交 |
| `gai commit` | 审查 → 建议信息 → 确认 → 提交 |
| `gai devflow` | 引导式串联：AI 暂存建议 → 审查 → 中英提交词 → 推送 |
| `gai push` | 推送当前分支（先检查是否有可推送内容） |
| `gai pull` | 拉取远程（先检查；分叉可选 merge / rebase） |
| `gai report` | 根据提交记录写工作总结 |
| `gai balance` | 查询 API Key 剩余额度（厂商支持时） |
| `gai usage` | 查看本地记录的大模型 token 用量历史 |
| `gai history` | 查看本地 gai 命令执行记录 |
| `gai config` | 查看 / 写入 `~/.gai/config.toml` |

## 命令参考

### `gai add`

包装 `git add`。未给路径时默认 `git add .`。

| 参数 | 说明 |
|------|------|
| `PATHS...` | 要暂存的路径；省略则为 `.` |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai add
gai add src/ README.md
gai add --cn -t
```

### `gai unadd`

包装 `git restore --staged`。**需确认**（默认否）。未给路径时撤销全部暂存。

| 参数 | 说明 |
|------|------|
| `PATHS...` | 要取消暂存的路径；省略则为 `.` |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai unadd --cn
gai unadd src/ --cn -t
```

### `gai uncommit`

`git reset --soft HEAD~1`。改动留在暂存区。**需确认**。

| 参数 | 说明 |
|------|------|
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai uncommit --cn
```

### `gai review`

只审查，不提交。只看 **已暂存** 内容。

| 参数 | 说明 |
|------|------|
| `--json` | 输出结构化 JSON |
| `--message-only` | 主要生成 commit message |
| `--cn` | 审查结论与摘要用简体中文 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai review --cn
gai review --json
```

### `gai commit`

审查 → 生成 Message → 确认 → 提交。

| 参数 | 说明 |
|------|------|
| `-m` / `--message` | 使用指定 Message（可仍做审查） |
| `-y` / `--yes` | 跳过交互确认 |
| `--no-review` | 跳过审查展示，只生成 Message |
| `--no-ai` | 完全不调 AI，必须同时带 `-m` |
| `--cn` | 中文审查结果 + 中文确认文案 |
| `--push` | 提交成功后推送到已配置的远程 |
| `-r` / `--remote` | 配合 `--push` 指定远程名（默认优先 `origin`） |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai commit --cn
gai commit --cn --push
gai commit -y --push -r origin
gai commit --no-ai -m "chore: release"
```

### `gai devflow`

一条命令串联日常流程：**AI 暂存建议 → 审查 → 中英提交词自选 → 确认推送**。每一步仍由你决定，不会全自动一把梭。

1. **add**：AI 建议暂存路径；`y` 采纳建议，`.` 全部暂存，`n` 手输路径  
2. **review**：审查 staged diff（带 `--cn` 时审查文案为中文；不带则可自选 cn/en）  
3. **commit**：同时给出英文 / 中文 Conventional Commits 候选，你选择或手输，再确认提交  
4. **push**：再确认是否推送（可跳过，提交仍留在本地）

```bash
gai devflow --cn
gai devflow
gai devflow --cn -r origin
```

| 参数 | 说明 |
|------|------|
| `--cn` | 界面与审查用简体中文；提交词仍提供中英两种 |
| `-r` / `--remote` | 最后一步 push 的远程名 |
| `-t` / `--trace` | 每一步结束后打印该步执行的 git 命令 |

### `gai push`

推送到**已配置**的远程（不会帮你 `git remote add`）。推送前 `fetch` 并检查是否领先远程；**没有可推送内容时提示，不会报成功**。

| 参数 | 说明 |
|------|------|
| `-r` / `--remote` | 远程名；默认 `origin`，否则唯一 remote |
| `-y` / `--yes` | 跳过确认 |
| `-u` / `--set-upstream` | 强制 `git push -u` |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

无 upstream 时自动 `git push -u <remote> <branch>`。

```bash
gai push --cn
gai push -y
gai push -r origin -u --cn
```

### `gai pull`

先 `fetch` 再决定是否拉取：

- 没有可拉取内容 → 提示后退出
- 有可拉取内容 → 显示待拉取数，**确认后再拉**
- 工作区有未提交改动 → 说明风险；`--yes` **直接拒绝**，避免覆盖
- 本地与远程同时领先（分叉） → 选 `merge` / `rebase` / 取消（`--yes` 默认 merge）
- 合并 / 变基冲突 → 友好提示去解决冲突

| 参数 | 说明 |
|------|------|
| `-r` / `--remote` | 远程名；默认 `origin`，否则唯一 remote |
| `-y` / `--yes` | 跳过确认（脏工作区仍会拒绝） |
| `--rebase` | `git pull --rebase` |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai pull --cn
gai pull --rebase --cn
gai pull -y
```

### `gai report`

根据 `git log` 生成可粘贴的工作总结。

| 参数 | 说明 |
|------|------|
| `-s` / `--since` | 起始，默认 `7d`；支持 `2w`、`1m`、`YYYY-MM-DD`、`alltime` |
| `-u` / `--until` | 结束（可选） |
| `-a` / `--author` | 作者；`me` = 当前 git 用户 |
| `-n` / `--max-count` | 最多纳入提交数，默认 `100`（`--alltime` 升为 `500`） |
| `--alltime` | 全部历史（等价 `--since alltime`） |
| `--per` | 团队模式下按人列出具体工作 |
| `-o` / `--out` | 导出 Markdown；裸 `-o` = 当前目录默认文件名；缺目录则创建；非法路径回退 |
| `--no-stat` | 不把 shortstat 送给模型 |
| `--json` | 输出结构化 JSON |
| `--cn` | 用简体中文写总结 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai report --cn
gai report --cn --per -o 周报.md
gai report --since 2026-09-01 --until 2026-09-23 --json
```

### `gai usage`

查看 **本地** 记录的大模型调用历史（多数厂商不提供按 API Key 的历史用量接口，因此由 gai 在每次成功调用后写入一行摘要）。

每条记录包含：时间、Git 用户、**仓库根目录名**（`repo_name`）、**远程名**（`remote_name`，无远程则为 `null`）、厂商、模型、token、命令动作（`review` / `commit` / `report`），以及便于事后分析的字段：

- `action_detail`：细分用途（`review` / `commit-message` / `review+message` / `report`）
- `branch`、`files_count`、`diff_chars`、`truncated`（审查/提交规模）
- `commit_count`、`since`（工作总结范围）
- `ok`、`duration_ms`、`error_kind`（成功/失败与耗时）
- `gai_version`

不写 prompt / diff / 模型正文。日志默认在**当前仓库根目录** `.gai/usage.jsonl`（已 `.gitignore`）；可用 `GAI_USAGE_LOG` 覆盖。过大时自动轮转。

```bash
gai usage --cn
gai usage --report --cn                 # 固定写入 .gai/usage-report.html（覆盖同步）
gai usage --open --cn                   # 同步并打开浏览器（隐含 --report）
gai usage --serve --cn                  # 本地 HTTP 打开，刷新更稳定（隐含 --report）
gai usage --report --since 7d --cn      # 只把近 7 天数据同步进报告
gai usage --since 7d --group action --cn
gai usage --action commit -n 50 --cn
gai usage --user alice --json
```

`--report` / `--open` / `--serve` 会读取当前项目的 `.gai/usage.jsonl`，**覆盖写入** `.gai/usage-report.html`，并同步 `.gai/usage-data.js`。首次有 LLM 用量写入时也会自动生成报告壳（不必先跑 `--report`）。报告页支持：

- **刷新**：加载最新 `usage-data.js`（日常 `gai` 调用会自动更新；`file://` 被拦时改用 `--serve`）
- **导出 CSV**、最近记录分页
- **中 / 英**、**日间 / 夜间**主题（与指南共用 `gai-ui-lang` / `gai-ui-theme`）

可按仓库筛选：

- **全部项目**：总览图（按仓库用量、仓库×动作热力图等）
- **某个仓库**：仓内详情（按分支用量、动作×分支热力图等）

共用图：趋势 / 成功失败 / 输入输出 / 耗时 / 动作 / 厂商 / 模型 / 用户。远程与仓库绑定，不做单独筛选。命令行会打印可点击的 `file://` 链接；再次执行会与最新日志同步。

| 参数 | 说明 |
|------|------|
| `-n` / `--limit` | 控制台最多显示条数（默认 20；`0` 不限制；`--report` 忽略此限制） |
| `-s` / `--since` | `7d` / `2w` / `YYYY-MM-DD` / `alltime` |
| `-a` / `--action` | 过滤动作：`review` / `commit` / `report` |
| `--provider` | 按厂商 id 过滤（如 `deepseek`） |
| `-u` / `--user` | 按 git 用户名或邮箱子串过滤 |
| `-g` / `--group` | 额外汇总：`action` / `provider` / `model` / `user` |
| `--report` | 同步生成 `.gai/usage-report.html` 可视化报告 |
| `--open` | 打开浏览器（隐含 `--report`） |
| `--serve` | 本地 HTTP 打开（隐含 `--report`；刷新更稳） |
| `--json` | JSON 输出 |
| `--cn` | 中文输出 |
| `-t` / `--trace` | 打印链路（本命令通常无 git） |

### `gai guide`

生成本地可视化使用指南，固定写入 **`.gai/guide.html`**（中英双语同一文件）。示例与 CLI 用法提示同源；支持命令搜索与深链（如 `guide.html#commit`）。

```bash
gai guide --cn           # 首屏中文
gai guide --open --cn    # 生成并用浏览器打开
gai guide --serve --cn   # 本地 HTTP 打开
gai guide                # 首屏英文
```

页面内可随时切换语言 / 主题（与用量报告共用偏好）；命令行会打印可点击的 `file://` 链接。再次执行会覆盖同步。

| 参数 | 说明 |
|------|------|
| `--cn` | 首屏使用中文（页面内仍可切到英文） |
| `--open` | 用默认浏览器打开 |
| `--serve` | 用本地 HTTP 打开 |

### `gai history`

查看 **本地** 记录的 gai 命令执行历史（与 `gai usage` 的 token 用量分开）。每次通过 `gai` 入口执行的子命令都会追加一行到仓库 `.gai/commands.jsonl`（已 `.gitignore`）；可用 `GAI_HISTORY=0` 关闭，或用 `GAI_HISTORY_LOG` 覆盖路径。密钥类参数（如 `--api-key`）会掩码为 `***`。

```bash
gai history --cn
gai history --report --cn               # 固定写入 .gai/history-report.html（覆盖同步）
gai history --open --cn                 # 同步并打开浏览器（隐含 --report）
gai history --serve --cn                # 本地 HTTP 打开，刷新更稳定（隐含 --report）
gai history --command commit --cn
gai history --failed --since 7d --cn
gai history -n 50 --json
```

`--report` / `--open` / `--serve` 会读取 `.gai/commands.jsonl`，**覆盖写入** `.gai/history-report.html`，并同步 `.gai/history-data.js`。首次有命令记录写入时也会自动生成报告壳。报告页与用量报告交互一致：

- **全部项目 / 单仓库**筛选（跨仓对比 vs 仓内详情）
- **刷新**、**导出 CSV**、最近记录分页
- **中 / 英**、**日间 / 夜间**（共用 `gai-ui-lang` / `gai-ui-theme`）

| 参数 | 说明 |
|------|------|
| `-n` / `--limit` | 最多显示条数（默认 20；`0` 不限制；`--report` 忽略此限制） |
| `-s` / `--since` | `7d` / `2w` / `YYYY-MM-DD` / `alltime` |
| `-c` / `--command` | 按子命令名过滤（如 `commit`、`usage`） |
| `--failed` | 只看失败（非零退出码） |
| `--report` | 同步生成 `.gai/history-report.html` 可视化报告 |
| `--open` | 打开浏览器（隐含 `--report`） |
| `--serve` | 本地 HTTP 打开（隐含 `--report`；刷新更稳） |
| `--json` | JSON 输出 |
| `--cn` | 中文输出 |
| `-t` / `--trace` | 打印链路（本命令通常无 git） |

### `gai balance`

查询当前配置的 API Key **剩余额度**。

1. **先检查是否已配置 API Key**；未配置则提示去设置
2. 根据 `base_url` 识别厂商并查询（换厂商后一般不用改命令）：
   - **已支持**：DeepSeek、硅基流动、Moonshot/Kimi、OpenRouter
   - **暂未接入公开余额接口的厂商**（如 OpenAI、通义）：提示当前厂商与模型，并列出已支持列表

```bash
gai balance --cn
gai balance
```

| 参数 | 说明 |
|------|------|
| `--cn` | 中文输出 |
| `-t` / `--trace` | 打印链路（本命令通常无 git） |

### `gai config`

查看或写入 `~/.gai/config.toml`。

| 参数 | 说明 |
|------|------|
| `--show` | 显示当前生效配置（密钥已掩码） |
| `--api-key` | 设置 API Key |
| `--base-url` | 设置 API Base URL |
| `--model` | 设置模型名 |
| `--timeout` | HTTP 超时秒数 |
| `--max-diff-chars` | 送入模型的文本最大字符数 |
| `--cn` | 与 `-h` 联用显示中文帮助 |
| `-t` / `--trace` | 若未执行 git，提示未涉及 git 操作 |

## 交互与错误提示

- **用法纠错**：子命令 / 参数拼写错误、少写 `-` / `--` 时，提示相近命令并给出带说明的正确示例（随 `--cn` 中英文切换）。
- **时间范围**：`--since` 晚于 `--until`、非法 `YYYY-MM-DD` 会报错，并附正确格式示例。
- **大模型**：未配置 Key、鉴权失败、欠费 / 配额、限流、超时、网络失败等有分类提示。超时 / 429 / 5xx **自动重试最多 3 次**。
- **余额查询**：`gai balance` 先确认 API Key；按 `base_url` 识别厂商查询（DeepSeek / 硅基流动 / Moonshot·Kimi / OpenRouter）；未接入的厂商会提示当前厂商与模型。
- **Git**：非仓库、无 remote、鉴权失败、推送被拒、拉取冲突、脏工作区等有可读说明；`--trace` 时额外打印原始详情。
- **用量**：黄色一行显示本次调用；有 token 合计时只显示接口返回值，**不估算**。历史用量见 `gai usage`（本地 JSONL）。
- **命令记录**：每次 `gai …` 执行会写入 `.gai/commands.jsonl`；用 `gai history` / `gai history --report` 查看，`GAI_HISTORY=0` 可关闭。

## 设计要点

- 审查 / 提交只看 staged diff（`git diff --cached`）。
- 不拦截原生 git：可用 `--no-ai -m` 或直接 `git commit` / `git push`。
- Core（`review.py` / `report.py` / `git_ops.py` / `llm/`）不依赖终端交互；CLI 负责展示与确认。
- 默认忽略锁文件与常见二进制；超大输入会截断并提示。
- 版本号以 `pyproject.toml` 为准（`gai --version` 读取安装包元数据）。

## 项目结构

```
CodeReviewAgent/
  pyproject.toml
  README.md
  src/gai/
    cli.py           # 入口：add / unadd / uncommit / review / commit / devflow / push / pull / report / usage / history / guide / balance / config / completion
    devflow.py       # gai devflow：暂存建议与中英提交词
    command_history.py # .gai/commands.jsonl 命令执行记录
    history_report.py  # commands.jsonl → .gai/history-report.html
    guide.py         # .gai/guide.html 可视化使用指南（中英双语）
    completion_cmd.py # shell Tab 补全安装 / 查看
    cli_usage.py     # 子命令 / 参数拼写纠错
    errors.py        # 友好错误文案
    help_i18n.py     # -h --cn 帮助语言
    git_ops.py       # git subprocess
    config.py        # 环境变量与 ~/.gai/config.toml
    review.py        # 审查引擎
    report.py        # 提交记录 → 工作总结
    llm/
      client.py      # OpenAI 兼容客户端（含重试）
      balance.py     # 厂商余额查询
      usage.py       # 本次调用与 token 统计
      history.py     # 本地用量 JSONL 持久化
      usage_report.py # usage.jsonl → .gai/usage-report.html
      prompts.py     # Prompt 模板
  tests/
```

## 开发

```bash
python -m pip install -e ".[dev]"
python -m pytest
```
