# 0020 · 角色会话按 Run 复用，Cursor 加载项目与用户配置，MCP 全局可见

- 状态：已实现
- 日期：2026-11-11
- 关联：[0009](0009-runtime-correctness.md)（C4 会话续接）；[0019](0019-default-flow-agent-steps-as-activities.md)。

## 背景

1. **会话粒度。** Cursor Agent 与 Codex Thread 的会话标识原为（Run、节点、角色、工作目录、模型、角色定义、推理强度）。同一角色在不同节点各建一个会话，上下文不延续；role.md 只在会话首条消息发送，因此每进入一个新节点就重复发送一次。预期是同一 Run 中的角色智能体只在首次发送时带上 role.md。
2. **Cursor 配置未加载。** `LocalAgentOptions` 未设置 `setting_sources`。Cursor SDK 默认只加载内联传入的配置；以真实 SDK 实测，默认情况下智能体看不到任何 Skill、MCP 服务器与工作区规则。节点上选择的 Skill 和 MCP 只停留在提示词中，无法实际调用。

## 决定

1. **会话标识去掉节点 ID。** 两个后端的标识改为（Run、角色、工作目录、模型、角色定义，以及显式推理强度）。同一角色在整个 Run 中共用一个会话，跨节点延续上下文，role.md 只随首条消息发送一次。对话记录仍按节点分目录写入 `conversations/nodes/<节点>/`。
2. **以下情况仍另开会话**：中途更换模型或推理强度、修改 role.md、工作目录不同（可写的并行支路各有快照工作树）。
3. **同一 Agent 串行发送。** 只读并行支路共用本轮工作目录，同一角色会落到同一 Agent；Cursor 后端按会话标识加进程内锁，逐条发送。Codex 后端原本就在会话文件锁内完成整轮调用。
4. **加载项目与用户配置。** Cursor 本地智能体设置 `setting_sources=("project", "user")`，加载工作树 `.cursor/` 与 `~/.cursor/` 中的 `mcp.json`、规则与 Skill。
5. **MCP 是全局配置。** 与 Cursor IDE 一致，后端加载的 MCP 服务器对所有角色可见，不按角色或节点选择。运行页去掉节点的 MCP 选择，接口与运行状态只保存节点的 Skill，旧 Run 中残留的 `mcp` 字段读取时忽略；配置页 Agent 下按所选后端只读列出 MCP 服务器（`GET /api/config/tools?backend=&project_id=`）：Cursor 读取所开项目工作区与用户目录的 `.cursor/mcp.json`，Codex 读取 `$CODEX_HOME/config.toml` 的 `mcp_servers`。
6. **Skill 按节点提示优先使用。** 节点所选 Skill 写入提示词「这一步优先使用下面的 Skill」，不再声称「只使用」；未选时由 Agent 按需选用。

## 后果

- 后续节点能看到同一角色在前序节点的推理与工具调用记录，减少重复读取；代价是上下文持续增长，token 成本随 Run 变长而上升。
- 本决定之前创建的会话文件含节点 ID，新调用不会再命中，旧 Run 续跑时各角色会新建一个会话。
- 实测加载两层配置后，智能体可见项目 Skill、用户层全部 Skill、`~/.cursor/mcp.json` 中的 MCP 服务器与项目规则。用户层的全局规则（例如回复语言、并行度限制）同样对工厂角色生效，需留意与 role.md 的要求是否冲突。
- 未采用按角色过滤 MCP：实测在加载项目与用户配置层时，内联传入的 `mcp_servers` 与 `mcp.json` 中的服务器合并，无法收窄；`disallowed_tools` 只能整体去掉 MCP。若要过滤，只能放弃用户层（连带用户层 Skill 与规则）并由工厂自行转写 `mcp.json`，代价与 IDE 配置不一致的风险都较高。写操作类工具的风险由 role.md 职责约束与 MCP 服务端权限控制；不该给工厂使用的服务器，从对应的 `mcp.json` 中移除。
