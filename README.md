# gai — Local Git Commit & Code Review Agent

本地 CLI：对 **staged** 变更做 AI Code Review，生成 Conventional Commits 提交信息，确认后再执行 `git commit`。

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
| `GAI_MAX_DIFF_CHARS` | 送入模型的 diff 最大字符数 | `80000` |

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

必须在 **git 仓库**目录下使用，且只审查已暂存内容：

```bash
git add .                 # 先暂存
gai review                # 只审查，不提交
gai commit                # 审查 → 建议 Message → 确认 → 提交
gai review --cn           # 中文审查结果
gai commit --cn           # 中文审查 + 中文交互文案
```

`gai commit` 流程：

1. 打印 Review（严重度 / 位置 / 问题 / 建议）
2. 展示建议的 Commit Message
3. 询问是否采纳并提交（`--cn` 时为中文提示）
4. 确认后执行 `git commit -m "..."`

## 命令参考

### `gai review`

只审查，不提交。

| 参数 | 说明 |
|------|------|
| `--json` | 输出结构化 JSON（供编辑器 / 插件复用） |
| `--message-only` | 主要生成 commit message |
| `--cn` | 审查结论与摘要用简体中文；终端表头等界面文案同步中文 |

### `gai commit`

审查 → 生成 Message → 确认 → 提交。

| 参数 | 说明 |
|------|------|
| `-m` / `--message` | 使用指定 Message（可仍做审查） |
| `-y` / `--yes` | 跳过交互确认 |
| `--no-review` | 跳过审查展示，只生成 Message |
| `--no-ai` | 完全不调 AI，必须同时带 `-m` |
| `--cn` | 中文审查结果 + 中文确认文案 |

示例：

```bash
gai commit -y
gai commit --no-review
gai commit -m "fix: handle nil ptr"
gai commit --no-ai -m "chore: release"
gai commit --cn
gai review --json --cn
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
| `--max-diff-chars` | diff 截断上限 |

## 设计要点

- **只看 staged diff**（`git diff --cached`），与真正提交内容一致；未 `git add` 会提示先暂存。
- **不拦截原生 `git commit`**：可用 `--no-ai -m` 或直接 `git commit` 兜底。
- Core（`review.py` / `git_ops.py` / `llm/`）不依赖终端交互；CLI 只负责展示与确认。
- 默认忽略锁文件与常见二进制扩展名，避免浪费 token；超大 diff 会截断并提示。
- `--cn` 时：`issue` / `suggestion` / `summary` 为中文；`severity` 与 Conventional Commits 的 type 仍为英文，subject 可用中文。

## 项目结构

```
CodeReviewAgent/
  pyproject.toml
  README.md
  src/gai/
    cli.py           # typer 入口：review / commit / config
    git_ops.py       # git subprocess 封装
    config.py        # 环境变量与 ~/.gai/config.toml
    review.py        # 审查引擎与终端渲染
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

## 后续

第二阶段可用 `gai review --json` 对接 VS Code / Cursor 插件，复用同一审查引擎。
