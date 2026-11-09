# GeniStudio 架构

> 待默认流程第一版完成后补充其余章节。

## 总体架构

## 角色定义

每个角色在 `roles/<name>/role.md` 中定义：YAML 头部为结构化字段，正文为原则、价值观、工作方式与禁止事项。角色定义保持与场景无关；场景相关的工具与领域知识由场景配置提供，见下文"场景配置"。

| 字段 | 含义 |
|------|------|
| `name` | 角色标识，与目录名一致 |
| `title` | 中文名称 |
| `category` | `management`（管理角色）或 `execution`（执行角色） |
| `responsibilities` | 职责摘要，须与正文一致 |
| `inputs` | 角色读取的产物名称；引擎按此组装角色上下文 |
| `outputs` | 角色产出的产物名称 |
| `capabilities` | 角色对目标工作区所需的操作能力，见下文 |

## 产物与图状态

## 后端插件接口

### `capabilities` 的口径

`capabilities` 只描述角色对**目标工作区**（本轮任务的 git 工作树）的操作：

| 能力 | 含义 |
|------|------|
| `read_files` | 读取目标工作区中的文件 |
| `write_files` | 修改目标工作区中的文件 |
| `run_commands` | 在目标工作区中执行命令，例如构建、测试、git 操作 |

角色产出的产物（`outputs`）以结构化结果交回引擎，由引擎按 `config_plan` 保存，不计入 `write_files`。因此只产出报告、不改动目标仓库的角色（例如 QA、代码评审）无需 `write_files`。

运行前，引擎校验为角色所选的后端是否具备其声明的全部能力；不满足时拒绝启动该角色，不做降级执行。

## 场景配置

场景配置描述某类开发场景（例如 Python 小工具、Web 应用、NPU 算子开发）下工厂如何运转，至少包括：

- 使用的工作流程；
- 各类产物的模板与规范，以及配置管理规则；
- 为各角色分配的技能与 MCP 工具；
- 为各角色追加的领域原则，例如"算子开发场景下，架构师须核对硬件对齐约束"。

引擎在运行时把场景配置中的工具与领域原则叠加到角色定义上。角色定义本身不声明具体工具与领域知识，以便同一角色在不同场景复用。场景配置由配置管理员维护。

### 场景、项目与单次运行（配置栈）

针对**具体目标项目**，模板与流程可在工厂默认之上**覆盖或裁剪**，合并优先级为：**单次 Run 输入 > 项目 `projects/<id>/project.yaml` > 场景 `scenarios/<key>/` > 工厂默认**。模板通过 **`template_path` 决议**（项目 → 场景 templates → `templates/artifacts/`）与可选 **`omit_sections`** 裁剪。未选定流程时，Workflow Profile（`skip_nodes`、`features.design_track`、关卡开关等）作用于默认 Python 图。项目选定 `workflows/<id>/workflow.yaml` 时，当轮的图按该流程的节点编译，见 [ADR 0005](decisions/0005-selected-workflow-compiles-run-graph.md)。配置管理员在 **`config_plan`** 中登记本轮生效路径与裁剪项。

详见 [ADR 0002：场景配置、项目配置与流程/模板裁剪](decisions/0002-scenario-project-config-and-cropping.md)。

### 设计链（UX / UI / 美工）

默认流程在 **需求确认关卡之后** 的主链路 **不包含** 体验/界面/美工节点，直接进入预算粗估与架构。仅当满足下列之一时才走 ``ux_designer → ui_designer → visual_designer``：

1. 运行输入显式设置 ``design_track_enabled: true``；
2. 合并后的 Workflow Profile 中 ``workflow.features.design_track: true``（见 ``scenarios/<key>/scenario.yaml``，例如 ``web_app``）。

未指定场景、未知 ``scenario_key`` 或 ``design_track_enabled: false`` 时均 **跳过** 设计链。引擎在跳过时不应调度 UX/UI/美工 Agent。

## 人类通信（HITL）

人类与工厂的 **业务对话** 仅经 **项目经理** 语义呈现；引擎在关卡暂停、澄清或升级时进入 `awaiting_human`，由人类通过下列 **一期** 通道提交批复或答复后 Resume Run：

| 通道 | 职责 |
|------|------|
| Web | 全功能：待办、产物摘要、关卡、长文本澄清 |
| 飞书 | 即时通知、卡片按钮、短文本回复 → HITL API |

微信系（含企业微信）**一期不做**。角色之间仍只通过 **产物** 协作，不使用飞书机器人群聊。通道差异、审计规则与状态字段见 [ADR 0003：项目经理人类触达](decisions/0003-pm-human-hitl-and-im-channels.md)。

### Web HITL API（一期）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 最小待办 UI |
| POST | `/api/runs` | 启动 Run（`human_request`、可选 `scenario_key` / `project_id`） |
| GET | `/api/runs/{thread_id}` | 状态、`phase`、`awaiting_human`、state 摘要 |
| POST | `/api/runs/{thread_id}/hitl` | 提交 `gate_decision` + `human_reply`，续跑至下一 interrupt 或结束 |

启动本地 Web：`geni-studio-web` 或 `python -m geni_studio.web.app`（默认 `127.0.0.1:8765`）。飞书 **入站**（卡片/消息 → HITL）仍待接；**出站**通知见 [ADR 0004](decisions/0004-feishu-hitl-via-lark-cli.md)。

#### 飞书接到 GeniStudio（推荐：官方 lark-cli）

适用：**公司租户未开开放平台**，用 **个人开发者账号** 创建应用。

1. **本机 lark-cli**  
   - `lark-cli config init --new`，按提示绑定个人应用的 App ID / Secret。  
   - 验证：`lark-cli auth status --json --verify`  
   - 发消息测试：`lark-cli im +messages-send --as bot --chat-id oc_xxx --text "ping"`

2. **仓库 `.env`**  
   - `GENI_STUDIO_LARK_BACKEND=lark_cli`（默认）  
   - `GENI_STUDIO_PUBLIC_BASE_URL`：Web HITL 链接前缀（通知正文中的跳转）  
   - **不必** 填写 `LARK_APP_SECRET`（除非改用 `env_bot` 后端）

3. **项目 YAML**（`/config` 可编辑）  

   ```yaml
   hitl:
     feishu:
       notify_chat_id: oc_xxx
   ```

4. **行为**  
   - Run 进入 `awaiting_human` 时，GeniStudio 调用 `lark-cli im +messages-send --as bot` 推送 PM 文本 + Web 链接。  
   - 人类在 Web 提交 `gate_decision`；与飞书入站回调等价的路径后续再接。

5. **备选 `env_bot`**  
   - 企业已开开放平台且希望在 `.env` 存凭据时：设 `GENI_STUDIO_LARK_BACKEND=env_bot` 并填写 `LARK_APP_ID` / `LARK_APP_SECRET`（直连发送待实现时可仍用 lark-cli）。

6. **身份边界**  
   - PM 对外须为 **Bot 应用身份**（lark-cli `--as bot`），**不要** 用 lark-tools 员工 Cookie `send` 冒充项目经理。

### Web 配置（一期）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/config` | 配置 UI |
| GET | `/api/config/scenarios` | 场景列表（L1） |
| GET | `/api/config/scenarios/{key}` | 场景 YAML（只读） |
| GET/PUT | `/api/config/projects/{id}` | 项目 YAML 读/写 |
| POST | `/api/config/projects` | 新建项目目录 |
| GET | `/api/config/effective` | 合并后 profile 预览 |
| GET | `/api/config/settings` | `.env` 密钥是否已配置（不回传明文） |

## 人工关卡

流程在需求确认、架构评审、最终交付等节点 **interrupt** 等待人类；批复须写 `baseline_log` 并与 Web 或飞书 HITL 提交对齐。PM 在关卡前的 **澄清** 使用同一套待办机制，不限于三处固定关卡。

## 复盘与进化
