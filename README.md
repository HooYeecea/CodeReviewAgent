# gai — Local Git Commit & Code Review Agent

本地命令行工具：对 **staged** 变更做 AI Code Review，生成符合 Conventional Commits 的提交信息，确认后再执行 `git commit`。

## 安装

```bash
cd CodeReviewAgent
python -m pip install -e ".[dev]"
```

安装后可用：

```bash
gai --help
gai --version
```

## 配置

支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义兼容模式等）。

**环境变量（优先）：**

| 变量 | 含义 |
|------|------|
| `GAI_API_KEY` 或 `OPENAI_API_KEY` | API Key |
| `GAI_BASE_URL` 或 `OPENAI_BASE_URL` | Base URL，默认 `https://api.openai.com/v1` |
| `GAI_MODEL` | 模型名，默认 `gpt-4o-mini` |
| `GAI_TIMEOUT` | 超时秒数 |
| `GAI_MAX_DIFF_CHARS` | 送入模型的 diff 最大字符数 |

**或写入用户配置：**

```bash
gai config --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
gai config --show
```

配置文件路径：`~/.gai/config.toml`（优先级：环境变量 > 配置文件 > 默认值）。

## 日常用法

```bash
# 1. 照常改代码并暂存
git add .

# 2. 只做审查（不提交）
gai review

# 3. 审查 + 建议 Message + 确认后提交
gai commit
```

交互示例：

1. 终端打印 Review 表格（严重度 / 位置 / 问题 / 建议）
2. 展示建议的 Commit Message
3. 询问：`Adopt this message and commit? [Y/n]`
4. 确认后执行底层 `git commit -m "..."`

### 常用参数

```bash
gai commit -y                          # 跳过确认（脚本用）
gai commit --no-review                 # 只生成 Message，不做审查展示
gai commit -m "fix: handle nil ptr"   # 使用你指定的 Message（仍可做审查）
gai commit --no-ai -m "chore: release" # 完全跳过 AI，必须带 -m
gai review --json                      # 机器可读输出（供后续 VS Code 插件复用）
```

## 设计要点

- **只看 staged diff**（`git diff --cached`），与真正提交内容一致。
- **不拦截原生 `git commit`**：永远可用 `--no-ai -m` 或原生 git 兜底。
- Core（`review.py` / `git_ops.py` / `llm/`）不依赖终端交互，CLI 只负责展示与确认。
- 默认忽略锁文件与常见二进制扩展名，避免浪费 token。

## 开发

```bash
python -m pytest
```

## 后续

第二阶段可用 `gai review --json` 对接 VS Code 插件侧边栏，复用同一审查引擎。
