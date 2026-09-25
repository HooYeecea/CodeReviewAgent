# gai — Local Git Commit & Code Review Agent

本地 CLI：对 **staged** 变更做 AI Code Review、生成 Conventional Commits 提交信息，并可根据提交记录生成**工作总结**（写周报/日报用）。

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
gai commit -h --cn     # 子命令中文帮助
gai report -h --cn
gai push -h --cn
gai config -h --cn
```

帮助说明：

- 所有命令支持 `-h` / `--help`
- 与 `--cn` 联用时，帮助文案为简体中文（如 `gai -h --cn`、`gai commit -h --cn`）
- 子命令上的 `--cn` 仍同时控制实际输出语言（审查 / 报告 / 推送提示等）

安装后会在当前 Python 的 `Scripts` 目录生成 `gai` 启动器。只要该目录在 PATH 中，即可在任意 git 仓库目录使用（无需每个项目再装一次）。

## 配置

支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义兼容模式 / 硅基流动等）。

**优先级：环境变量 > `~/.gai/config.toml` > 默认值**

### 方式一：环境变量（推荐）

| 变量 | 含义 | 默认 |
|------|------|------|
| `GAI_API_KEY` 或 `OPENAI_API_KEY` | API Key | （必填） |
| `GAI_BASE_URL` 或 `OPENAI_BASE_URL` | API Base URL | `https://api.openai.com/v1` |
| `GAI_MODEL` | 模型名 | `gpt-4o-mini` |
| `GAI_TIMEOUT` | 请求超时（秒） | `60` |
| `GAI_MAX_DIFF_CHARS` | 送入模型的文本最大字符数 | `80000` |

Windows：在「系统属性 → 环境变量 → 用户变量」中新建上述变量。修改后需**重新打开**终端 / IDE 才会生效。

PowerShell 临时设置（仅当前窗口）：

```powershell
$env:GAI_API_KEY = "sk-xxx"
$env:GAI_BASE_URL = "https://api.deepseek.com/v1"
$env:GAI_MODEL = "deepseek-chat"
```

### 方式二：配置文件

```bash
gai config --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
gai config --show
```

配置写入：`~/.gai/config.toml`。

## 日常用法

必须在 **git 仓库**目录下使用。

### 提交前审查

只审查 **已暂存** 内容：

```bash
gai add                   # 包装 git add .（也可用 git add .）
gai add src/              # git add src/
gai review                # 只审查，不提交
gai commit                # 审查 → 建议 Message → 确认 → 提交
gai review --cn
gai commit --cn
gai commit --cn --push          # 提交成功后推送到已配置的 remote
gai push --cn                   # 仅推送当前分支（无可推送时提示）
gai push -y --cn
gai pull --cn                   # 检查后确认再拉取（无可拉取时提示）
gai pull -y --cn
gai add --cn -t                 # 暂存并打印底层 git 链路
gai unadd --cn                  # 撤销暂存（需确认）
gai uncommit --cn               # 撤销最近一次提交（soft，需确认）
gai commit --cn --trace         # 提交过程打印 git 命令链路
gai config --show --trace --cn  # 未跑 git 时提示「本次未涉及 git 操作」
```

需要看清底层执行了哪些 git 时，加 `--trace` / `-t`。若本次没有跑过 git，会提示「本次未涉及 git 操作」（支持 `--cn`）。

### 根据提交记录写工作总结

```bash
gai report --cn                              # 默认最近 7 天（团队总览，含参与者）
gai report --cn --per                        # 团队总览 + 按人明细
gai report --since 14d --cn                  # 报告会写明「哪天至今天」
gai report --author me --cn                  # 只看自己的提交
gai report --since 2026-09-01 --until 2026-09-23 --author me --cn
gai report --alltime --cn
gai report --alltime --author me --cn
gai report --since alltime --author me --cn
gai report --cn -o                           # 导出：当前目录 + gai-report-日期.md
gai report --cn --per -o 周报.md             # 导出到当前目录指定文件名
gai report --cn -o .\reports\                # 目录不存在则自动创建
gai report --author me --cn -o 我的周报.md   # 单人报告也可导出
```

`--author me` 会按本仓库 `git config user.email`（否则 `user.name`）过滤。也可写具体名字/邮箱，例如 `--author "张三"`。

未指定 `--author` 时为**团队报告**：会列出参与人数、每人提交数与占比；加 `--per` 再按人展开具体工作。

`--since` 支持相对时间 `7d` / `2w` / `1m`、绝对日期 `2026-09-01`，以及 `alltime`。`--alltime` 与 `--since alltime` 等价。报告结果会把指令时间落成具体日历区间，例如 `--since 7d` → `2026-09-16 至今天（2026-09-23）`。

`-o` / `--out` 导出 Markdown（**单人 / 团队报告都可导出**）：

- 只写 `-o`：当前目录 + `gai-report-YYYY-MM-DD.md`
- `-o 周报.md`：当前目录指定文件名
- `-o D:\reports\week.md` 或 `-o .\reports\`：指定路径；**目录不存在则自动创建**
- 路径格式非法：提示错误并回退到当前目录默认文件名
- 导出成功后打印**最终完整路径**

## 命令参考

### `gai add`

暂存文件（包装 `git add`）。未给路径时默认 `git add .`。

| 参数 | 说明 |
|------|------|
| `PATHS...` | 要暂存的路径；省略则为 `.` |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai add
gai add .
gai add src/ README.md
gai add --cn -t
```

### `gai unadd`

撤销暂存（包装 `git restore --staged`）。**默认需确认**（确认提示默认否）。未给路径时撤销全部暂存。

| 参数 | 说明 |
|------|------|
| `PATHS...` | 要取消暂存的路径；省略则为 `.`（全部暂存区） |
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai unadd --cn
gai unadd src/ --cn -t
```

### `gai uncommit`

撤销**最近一次**提交（`git reset --soft HEAD~1`）。改动会保留在暂存区。**默认需确认**。

| 参数 | 说明 |
|------|------|
| `--cn` | 中文提示 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai uncommit --cn
gai uncommit --cn -t
```

### `gai review`

只审查，不提交。

| 参数 | 说明 |
|------|------|
| `--json` | 输出结构化 JSON |
| `--message-only` | 主要生成 commit message |
| `--cn` | 审查结论与摘要用简体中文 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

### `gai commit`

审查 → 生成 Message → 确认 → 提交。

| 参数 | 说明 |
|------|------|
| `-m` / `--message` | 使用指定 Message（可仍做审查） |
| `-y` / `--yes` | 跳过交互确认 |
| `--no-review` | 跳过审查展示，只生成 Message |
| `--no-ai` | 完全不调 AI，必须同时带 `-m` |
| `--cn` | 中文审查结果 + 中文确认文案 |
| `--push` | 提交成功后推送到已配置的远程仓库 |
| `-r` / `--remote` | 配合 `--push` 指定远程名（默认优先 `origin`） |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai commit -y
gai commit --no-review
gai commit -m "fix: handle nil ptr"
gai commit --no-ai -m "chore: release"
gai commit --cn
gai commit --cn --push
gai commit -y --push -r origin
```

### `gai push`

将当前分支推送到**已配置**的远程仓库（不会帮你 `git remote add`）。推送前会 `fetch` 并检查本地是否领先远程；**没有可推送的提交时提示「没有可推送的内容」**，不会再显示推送成功。

| 参数 | 说明 |
|------|------|
| `-r` / `--remote` | 远程名；默认用 `origin`，否则唯一 remote |
| `-y` / `--yes` | 跳过确认 |
| `-u` / `--set-upstream` | 强制 `git push -u` |
| `--cn` | 中文提示文案 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

若当前分支没有 upstream，会自动使用 `git push -u <remote> <branch>` 建立跟踪。

```bash
gai push --cn
gai push -y
gai push -r origin -u --cn
```

前提：仓库已配置 remote（例如 `git remote -v` 能看到 `origin`），并且本机具备推送权限（SSH / HTTPS 凭证）。

### `gai pull`

从已配置的远程拉取更新。先 `fetch` 检查是否有可拉取的提交：

- **没有可拉取内容** → 提示「没有可拉取的内容」，不执行 pull
- **有可拉取内容** → 显示待拉取提交数，**确认后再拉取**（默认不直接确认）

| 参数 | 说明 |
|------|------|
| `-r` / `--remote` | 远程名；默认用 `origin`，否则唯一 remote |
| `-y` / `--yes` | 跳过确认（仍会先检查是否有可拉取内容） |
| `--cn` | 中文提示文案 |
| `-t` / `--trace` | 打印底层 git 命令链路 |

```bash
gai pull --cn
gai pull -y
gai pull -r origin --cn
```

### `gai report`

根据 `git log` 生成可粘贴的工作总结（阶段摘要 / 重点 / 分类 / Markdown 正文）。

| 参数 | 说明 |
|------|------|
| `-s` / `--since` | 起始范围，默认 `7d`；也支持 `2w`、`2026-09-01`、`alltime` |
| `-u` / `--until` | 结束范围（可选） |
| `-a` / `--author` | 作者过滤；`me` 表示当前 `git` 用户 |
| `-n` / `--max-count` | 最多纳入的提交数，默认 `100`（`--alltime` 时自动升为 `500`） |
| `--alltime` | 全部历史（等价于 `--since alltime`） |
| `--per` | 团队模式下按人列出具体完成内容 |
| `-o` / `--out` | 导出 Markdown；裸 `-o`=当前目录默认文件名；缺目录则创建；非法路径回退 |
| `--no-stat` | 不把 shortstat 送给模型 |
| `--json` | 输出结构化 JSON |
| `--cn` | 用简体中文写总结（适合直接贴进周报） |
| `-t` / `--trace` | 打印底层 git 命令链路（如 git log） |

```bash
gai report --cn
gai report --cn --per
gai report --since 7d --author me --cn
gai report --since 2026-09-01 --until 2026-09-23 --author me --cn
gai report --alltime --cn
gai report --alltime --author me --cn
gai report --since alltime --author me --cn
gai report --cn -o
gai report --cn --per -o 周报.md
gai report --cn -o D:\reports\week.md
gai report --author me --cn -o 我的周报.md
gai report --since 2026-09-01 --until 2026-09-23 --json
```

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
| `-t` / `--trace` | 若未执行 git，提示「本次未涉及 git 操作」 |

## 设计要点

- **暂存**：可用 `gai add`（默认 `.`）；撤销暂存用 `gai unadd`（需确认）。
- **审查/提交**：只看 staged diff（`git diff --cached`）；未暂存会提示先 `gai add`。
- **撤销提交**：`gai uncommit` 使用 soft reset，改动留在暂存区（需确认）。
- **友好错误提示**：LLM（鉴权/欠费/限流/超时等）与常见 Git/时间范围错误会给出中英文可读说明；`--cn` 切换文案，`--trace` 时额外打印原始详情（若有）。
- **推送**：要求已配置 remote；推送前检查是否有可推送提交；无可推送时提示而非报成功。无 remote / 无权限时给出明确错误，可用原生 `git push` 兜底。
- **拉取**：`gai pull` 先检查远程是否有可拉取内容；有则确认后再拉，没有则提示。
- **时间范围**：`report` 会校验 `--since` 不得晚于 `--until`，非法日期会明确报错。
- **工作总结**：读 `git log`（默认排除 merge），结合 subject + shortstat 归纳；报告会标明指令对应的具体起止日期。
- **导出**：`-o` 支持裸参数默认命名；缺目录自动创建；非法路径回退当前目录；成功后打印完整路径。
- **`--trace` / `-t`**：打印本次实际执行的 git 命令；若未执行任何 git，提示未涉及 git 操作（支持 `--cn`）。
- **不拦截原生 git**：可用 `--no-ai -m` 或直接 `git commit` / `git push` 兜底。
- Core（`review.py` / `report.py` / `git_ops.py` / `llm/`）不依赖终端交互；CLI 只负责展示与确认。
- 默认忽略锁文件与常见二进制扩展名；超大输入会截断并提示。

## 项目结构

```
CodeReviewAgent/
  pyproject.toml
  README.md
  src/gai/
    cli.py           # typer 入口：add / unadd / uncommit / review / commit / push / pull / report / config
    git_ops.py       # git subprocess 封装
    config.py        # 环境变量与 ~/.gai/config.toml
    review.py        # 审查引擎与终端渲染
    report.py        # 提交记录 → 工作总结
    llm/
      client.py      # OpenAI 兼容客户端
      prompts.py     # Prompt 模板
  tests/
```

## 开发

```bash
python -m pip install -e ".[dev]"
python -m pytest
```
