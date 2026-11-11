# GeniStudio

<p align="center">
  <img src="src/geni_studio/web/static/help-overview.jpg" alt="GeniStudio：项目经理居中协调，架构、前端、后端、测试和运维各就各位。" width="1024" />
</p>

AI 软件工厂：接收人类需求，由项目经理、架构师、程序员、测试工程师、QA、财务 等角色 Agent 在工作流程约束下协作，在给定的预算范围内产出经过验证的软件；每轮任务结束后复盘并提出改进提案。

需求与决策见 [`docs/requirements.md`](docs/requirements.md)。

## 目录结构

```text
geni_studio/
├── AGENTS.md            在 Cursor 中开发本工厂时的入口
├── docs/                自包含的开发上下文：需求、架构、术语、决策记录、项目计划
├── roles/               角色定义；每个角色一个目录，含 role.md（YAML 头部为结构化字段，正文为原则与价值观）
├── rubrics/             复盘评分标准：roles/ 为各角色产物，workflow.yaml 为流程本身
├── src/geni_studio/
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

## 安装

完整步骤、核对命令和给 Agent 的执行契约见 [`docs/install.md`](docs/install.md)。在仓库根目录通常是这四步，然后打开 Web 页面。密钥只写在本机的 `.env`，不要提交。

1. 用 Python 3.12 创建虚拟环境：`uv venv --python 3.12`
2. 安装本仓库及开发依赖：`uv pip install -e ".[cursor,dev]"`
3. 复制环境文件：`cp .env.example .env`（已有 `.env` 时不要覆盖）
4. 启动 Web 页面：`geni-studio-web`。浏览器打开 `http://127.0.0.1:8765/`

只熟悉界面、不调用 Cursor 时，在配置页把后端选成 stub，不必填写密钥。

## 本地开发

```bash
uv venv --python 3.12
uv pip install -e ".[cursor,dev]"
cp .env.example .env
langgraph dev
```

`langgraph dev` 需要 `src/geni_studio/workflows/default.py` 中定义 `graph`。

### Web HITL（人工关卡）

```bash
uv pip install -e ".[dev]"
geni-studio-web
```

浏览器打开 `http://127.0.0.1:8765/`：启动 Run、在 `gate_*` 关卡批准/驳回并续跑；支持 PM 澄清与升级待办。REST 见 [`docs/architecture.md`](docs/architecture.md)「Web HITL API」。

### Cursor SDK 后端

图节点经 `invoke_role` 调用后端。默认选择 Cursor；SDK、凭证或桥接不可用时会报错。只演示流程时显式设置 `GENI_STUDIO_BACKEND=stub`。

```bash
export CURSOR_API_KEY=...
# export GENI_STUDIO_CURSOR_MODEL=<模型名>   # 可选，留空使用 SDK 默认模型
python scripts/smoke_cursor_backend.py       # Bridge + 密钥连通性
python scripts/smoke_feishu_hitl.py          # 需另开 geni-studio-web
geni-studio-web
```

### Codex SDK 后端

在项目虚拟环境中安装并启动：

```bash
uv pip install -e '.[codex,dev]'
export GENI_STUDIO_BACKEND=codex
export GENI_STUDIO_WORKSPACE=1
# export GENI_STUDIO_CODEX_MODEL=<模型名>  # 可选，留空使用 SDK 默认模型
# export GENI_STUDIO_CODEX_REASONING_EFFORT=high  # 可选，模型须支持该级别
.venv/bin/geni-studio-web
```

使用启动服务的同一系统用户登录 Codex，即可复用本机登录状态，无需另填 API Key；也可在配置页保存 `OPENAI_API_KEY`。环境中有该 Key 时优先使用 Key 登录。打开 `http://127.0.0.1:8765/`，为项目选择流程和目标 Git 工作区，在运行页启动任务。Codex 必须有有效工作区，不能把关闭工作区的模拟运行当作真实开发。

配置页选择 Codex 后，可设置「Codex 推理强度」并写入 `.env`，从新运行生效。留空或选择默认时沿用 Codex 配置，不固定为 medium；项目 YAML 的 `backends.<角色>.reasoning_effort` 可覆盖工厂设置，填写 `default` 表示该角色直接沿用 Codex 默认。

运行页点选活动节点后，右栏可分别选择该角色本轮的模型与推理强度，Cursor 与 Codex 后端均适用；推理级别来自所选模型在 SDK 目录中声明的能力，Cursor 的 Auto 模型不能指定推理强度。选择具体模型或继承已明确的默认模型后，会显示该模型支持的级别；「沿用项目 / 工厂设置」继承原配置，「沿用 Codex 默认」则跳过项目和工厂的推理设置。本轮选择随「保存 Run 配置」、复制及 Run 续跑保留。

模型列表与各模型支持的推理级别均从 Codex SDK 动态读取。明确选择模型后，推理选项随之更新；「模型建议」是 SDK 模型目录给出的建议，不代表本机配置当前生效值。列表加载失败时保留已有设置，刷新配置页可重试。

需要工厂自动判定测试是否通过时，在项目 YAML 中配置验证命令，例如：

```yaml
verification:
  command: python -m unittest discover -v
```

配置页的连通检查只检查 SDK 启动和认证状态；模型是否可调用，以实际任务结果为准。

### 飞书 HITL（lark-cli）

出站/入站见 [`tools/lark_cli/README.md`](tools/lark_cli/README.md) 与 ADR 0004，以及 [`docs/install.md`](docs/install.md)「接上飞书」。`geni-studio-web` 在本机有 `lark-cli` 时会默认拉起事件桥（`GENI_STUDIO_FEISHU_BRIDGE=1`），将卡片回调与 IM 文本转发到 `/api/webhooks/feishu`。若需关掉内嵌桥接，设 `GENI_STUDIO_FEISHU_BRIDGE=0` 后单独运行：

```bash
geni-studio-feishu-bridge --webhook http://127.0.0.1:8765/api/webhooks/feishu
```

项目 `project.yaml` 中配置 `hitl.feishu.notify_open_id` 或 `notify_chat_id`（示例见 `projects/_example/project.yaml`）。
