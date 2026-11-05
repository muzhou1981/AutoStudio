# auto_studio

AI 软件工厂：接收人类需求，由项目经理、架构师、程序员、测试工程师、QA、财务 等角色 Agent 在工作流程约束下协作，在给定的预算范围内产出经过验证的软件；每轮任务结束后复盘并提出改进提案。

需求与决策见 [`docs/requirements.md`](docs/requirements.md)。

## 目录结构

```text
auto_studio/
├── AGENTS.md            在 Cursor 中开发本工厂时的入口
├── docs/                自包含的开发上下文：需求、架构、术语、决策记录、项目计划
├── roles/               角色定义；每个角色一个目录，含 role.md（YAML 头部为结构化字段，正文为原则与价值观）
├── rubrics/             复盘评分标准：roles/ 为各角色产物，workflow.yaml 为流程本身
├── src/auto_studio/
│   ├── core/            产物模型、图状态、运行上下文
│   ├── roles/           加载角色定义，构建图节点
│   ├── workflows/       LangGraph 流程；每套流程一个模块
│   ├── backends/        Agent 后端插件（默认 Cursor SDK）
│   ├── workspace/       git 工作树隔离与权限约束
│   ├── gates/           人工关卡
│   ├── retro/           复盘：收集证据、打分、输出 Top3
│   └── evolution/       改进提案、版本记录、回归评测入口
├── evolution/           已批准的改进记录（纳入版本库）
├── evals/tasks/         基准任务集
├── tests/
├── runs/                每轮运行产出（不纳入版本库）
└── langgraph.json       LangGraph Studio 的图注册
```

## 本地开发

```bash
uv venv --python 3.12
uv pip install -e ".[cursor,dev]"
cp .env.example .env
langgraph dev
```

`langgraph dev` 需要 `src/auto_studio/workflows/default.py` 中定义 `graph`。

### Web HITL（人工关卡）

```bash
uv pip install -e ".[dev]"
auto-studio-web
```

浏览器打开 `http://127.0.0.1:8765/`：启动 Run、在 `gate_*` 关卡批准/驳回并续跑；支持 PM 澄清与升级待办。REST 见 [`docs/architecture.md`](docs/architecture.md)「Web HITL API」。

### Cursor SDK 后端

图节点经 `invoke_role` 调用后端。未配置时走 **Stub**；设置 `CURSOR_API_KEY` 后默认启用 Cursor Local Agent（亦可显式 `AUTO_STUDIO_BACKEND=cursor`，强制 Stub 用 `AUTO_STUDIO_BACKEND=stub`）。

```bash
export CURSOR_API_KEY=...
python scripts/smoke_cursor_backend.py   # Bridge + 密钥连通性
auto-studio-web
```

### 飞书 HITL（lark-cli）

出站/入站见 [`tools/lark_cli/README.md`](tools/lark_cli/README.md) 与 ADR 0004。本地桥接：

```bash
auto-studio-web   # 终端 1
auto-studio-feishu-bridge   # 终端 2：卡片 + IM 文本 → Webhook
```

项目 `project.yaml` 中配置 `hitl.feishu.notify_open_id` 或 `notify_chat_id`（示例见 `projects/_example/project.yaml`）。
