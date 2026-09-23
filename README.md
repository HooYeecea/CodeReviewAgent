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
```

### 根据提交记录写工作总结

```bash
gai report --cn                    # 默认最近 7 天，中文周报风格
gai report --since 14d --cn        # 最近 14 天
gai report --since 2026-09-01 --until 2026-09-23 --cn
gai report --author me --cn        # 只看当前 git 用户的提交
```

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

```bash
gai commit -y
gai commit --no-review
gai commit -m "fix: handle nil ptr"
gai commit --no-ai -m "chore: release"
gai commit --cn
```

### `gai report`

根据 `git log` 生成可粘贴的工作总结（阶段摘要 / 重点 / 分类 / Markdown 正文）。

| 参数 | 说明 |
|------|------|
| `-s` / `--since` | 起始范围，默认 `7d`；也支持 `2w`、`2026-09-01` |
| `-u` / `--until` | 结束范围（可选） |
| `-a` / `--author` | 作者过滤；`me` 表示当前 `git` 用户 |
| `-n` / `--max-count` | 最多纳入的提交数，默认 `100` |
| `--no-stat` | 不把 shortstat 送给模型 |
| `--json` | 输出结构化 JSON |
| `--cn` | 用简体中文写总结（适合直接贴进周报） |

```bash
gai report --cn
gai report --since 7d --author me --cn
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
- **工作总结**：读 `git log`（默认排除 merge），结合 subject + shortstat 归纳，不编造 log 里没有的工作。
- **不拦截原生 `git commit`**：可用 `--no-ai -m` 或直接 `git commit` 兜底。
- Core（`review.py` / `report.py` / `git_ops.py` / `llm/`）不依赖终端交互；CLI 只负责展示与确认。
- 默认忽略锁文件与常见二进制扩展名；超大输入会截断并提示。

## 项目结构

```
CodeReviewAgent/
  pyproject.toml
  README.md
  src/gai/
    cli.py           # typer 入口：review / commit / report / config
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
