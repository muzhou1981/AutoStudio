# 0008 · Codex SDK 作为可选 Agent 后端

- 状态：已接受
- 日期：2026-11-10

## 背景

需求 6 要求 Agent 后端可替换，默认仍是 Cursor SDK。Codex 提供 Python SDK `openai-codex`，能在指定工作目录里执行一轮任务，并保留线程以便继续对话。

## 决策

1. 工厂后端增加 `codex`。环境变量 `GENI_STUDIO_BACKEND=codex`，或项目里某个角色的 `backends.<角色>.backend` 写 `codex`。
2. 实现使用 `openai_codex.Codex`。工作目录是本轮工作区。沙箱使用 `Sandbox.workspace_write`，因此程序员和测试工程师所需的文件写入与命令执行由 Codex 提供。
3. 模型留空，或写成 `default` / `auto` 时，不向 SDK 传入模型，沿用 Codex 自己的默认模型。显式模型来自 `GENI_STUDIO_CODEX_MODEL` 或该角色在本轮选择的模型。
4. 同一轮、同一角色、同一工作目录和模型复用一条线程。角色说明只在创建线程时作为 `developer_instructions` 传入。
5. 本机已登录 Codex 时不必写密钥。尚未登录时，可用 `OPENAI_API_KEY` 调用 `login_api_key`。密钥不回显。
6. `openai-codex` 是可选依赖组 `codex`。未安装时，选中 codex 的角色拒绝启动，不降级到 Cursor。

## 后果

- 配置页可以选择 codex，并单独保存 Codex 模型与 OpenAI API Key。
- 测试用假的 Codex 客户端，不启动真实 Codex 进程。
