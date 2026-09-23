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
gai --version
```

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
git add .
gai review                # 只审查，不提交
gai commit                # 审查 → 建议 Message → 确认 → 提交
gai review --cn
gai commit --cn
gai commit --cn --push          # 提交成功后推送到已配置的 remote
gai push --cn                   # 仅推送当前分支
gai push -y --cn
```

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

### `gai review`

只审查，不提交。

| 参数 | 说明 |
|------|------|
| `--json` | 输出结构化 JSON |
| `--message-only` | 主要生成 commit message |
| `--cn` | 审查结论与摘要用简体中文 |

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

将当前分支推送到**已配置**的远程仓库（不会帮你 `git remote add`）。

| 参数 | 说明 |
|------|------|
| `-r` / `--remote` | 远程名；默认用 `origin`，否则唯一 remote |
| `-y` / `--yes` | 跳过确认 |
| `-u` / `--set-upstream` | 强制 `git push -u` |
| `--cn` | 中文提示文案 |

若当前分支没有 upstream，会自动使用 `git push -u <remote> <branch>` 建立跟踪。

```bash
gai push --cn
gai push -y
gai push -r origin -u --cn
```

前提：仓库已配置 remote（例如 `git remote -v` 能看到 `origin`），并且本机具备推送权限（SSH / HTTPS 凭证）。

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
| `--max-diff-chars` | 送入模型的文本截断上限 |

## 设计要点

- **审查/提交**：只看 staged diff（`git diff --cached`）；未 `git add` 会提示先暂存。
- **推送**：要求已配置 remote；无 remote / 无权限时给出明确错误，可用原生 `git push` 兜底。
- **工作总结**：读 `git log`（默认排除 merge），结合 subject + shortstat 归纳；报告会标明指令对应的具体起止日期。
- **导出**：`-o` 支持裸参数默认命名；缺目录自动创建；非法路径回退当前目录；成功后打印完整路径。
- **不拦截原生 git**：可用 `--no-ai -m` 或直接 `git commit` / `git push` 兜底。
- Core（`review.py` / `report.py` / `git_ops.py` / `llm/`）不依赖终端交互；CLI 只负责展示与确认。
- 默认忽略锁文件与常见二进制扩展名；超大输入会截断并提示。

## 项目结构

```
CodeReviewAgent/
  pyproject.toml
  README.md
  src/gai/
    cli.py           # typer 入口：review / commit / push / report / config
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
