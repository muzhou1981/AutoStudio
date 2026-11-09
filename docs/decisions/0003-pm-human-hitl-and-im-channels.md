# 0003 · 角色协作模型与项目经理人类触达（Web / 飞书）

- 状态：已接受
- 日期：2026-11-05

## 背景

需求规定角色之间通过产物协作；项目经理是工厂对人类的统一沟通渠道。一期 Web 入口需支持运行观测与输入，并 **明确要求** 项目经理具备 **飞书** 即时通信能力，以便关卡等待、需求澄清与升级处理时人类可及时响应。

个人微信无稳定官方 Bot；企业微信回调与飞书能力重叠且无法覆盖个人微信场景，**一期不纳入** 微信系通道。

## 决策

### 1. 角色之间：不做即时群聊

- Agent 之间 **不** 建立飞书机器人群聊或点对点 IM 作为主协作通道。
- 协作以 **LangGraph 图状态 + 落盘产物 + `change_request`** 为准；节点内对话仅存 `runs/<run_id>/transcripts/` 供调试与复盘。

### 2. 人类触达：仅经项目经理 persona + 引擎 HITL

- **唯一产品语义**：人类与工厂的业务对话（澄清、关卡批复、预算与升级决策）均视为与 **项目经理** 交互；其他角色不直接对人类开放 IM。
- **真相写入**：IM 中的结论须由引擎或 PM 节点 **结构化写回** state / 产物（如 `requirement_spec`、`baseline_log`），IM 聊天记录 **不** 单独作为验收或基线依据。

### 3. 一期通道（并列，共用同一 HITL API）

| 通道 | 一期范围 | 说明 |
|------|----------|------|
| **Web** | 必做 | 待办列表、关卡批准/驳回、澄清问答、Run 暂停/续跑；见需求 §13、§2.10 |
| **飞书** | 必做 | 单聊或应用机器人：推送「待人类」卡片/消息，接收文本与卡片按钮回调，转发至 HITL API |

两通道 **共用** 同一后端：`awaiting_human` 状态、提交 `human_reply` / `gate_decision`、Resume 同一 `thread_id`。Web 为全功能面；飞书以 **及时触达 + 轻量批复/短答** 为主，复杂编辑仍引导至 Web。

### 4. HITL 类型

| 类型 | 触发 | 人类动作 |
|------|------|----------|
| **Gate** | `interrupt_before` 关卡节点 | 批准 / 驳回 / 附言 → `baseline_log` |
| **PM 澄清** | PM 产出待确认问题（state 或 `requirement_spec` 附录） | 逐条答复 → 合并进需求说明 |
| **升级** | 财务预警、回退超限等经 PM 汇总 | 选择方案 → 写 state 后续跑 |

### 5. 实现边界（一期）

- 引擎提供 **通道无关** 的 HITL 接口；飞书适配层为 **通知 + inbound 消息映射**，不重复实现流程逻辑。
- 飞书出站优先 **官方 lark-cli**（Bot）；企业凭据直连见 [ADR 0004](0004-feishu-hitl-via-lark-cli.md)。lark-tools 不作为 GeniStudio 产品主路径。
- 配置：项目级绑定飞书会话（如 `feishu_chat_id` / 发起人 open_id）与 Run；密钥不进仓库。
- **不做**：多角色 Bot 群、在 IM 内直接修改未过模板的产物全文、IM 与 Web 双源冲突（以最后一次 **经 HITL API 校验** 的提交为准）。
- **一期不做**：微信、企业微信及任何微信系回调；后续若需另写 ADR。

## 状态字段（已实现于 `FactoryState` + `GraphRunService` 推断 `awaiting_human`）

```yaml
awaiting_human:
  kind: gate | pm_clarification | escalation
  since: ISO8601
  gate_id: gate_requirement_confirm | null
  questions: []          # pm_clarification
  summary: ""          # 展示用短文案
human_reply: ""        # L3 单次提交，消费后清空或归档到 run_record
gate_decision: approved | rejected | null
```

## 后果

- 一期 M1/M2 排期须包含 HITL API 与 **飞书** IM 适配（可与 Web 并行）。
- `roles/project_manager/role.md` 职责不变；IM 能力由 **场景/项目配置 + 引擎插件** 提供，不写入角色正文工具列表（与场景配置原则一致）。

## 相关

- 需求 [§13、§2.10](../requirements.md)
- [ADR 0001](0001-workflow-in-python-with-langgraph-studio.md)（transcripts 与 Studio）
