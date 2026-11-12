# 0019 · 默认流程的智能体步骤改为通用活动

- 状态：已实现
- 日期：2026-11-12
- 关联：[0015](0015-single-engine.md) 后果第二条；[0010](0010-structured-verdicts.md)（结构化结论）；[ui-ux §13](../design/ui-ux.md)。

## 背景

[0015](0015-single-engine.md) 之后，`factory_default` 由流程文件编译，但调用 Agent 的 16 个步骤仍是系统节点，复用 `default.py` 中手写的提示词与判定。普通活动的提示词由编译器拼装，包含输入产物、返工反馈和这一步选用的 Skill 与 MCP；系统节点不经过这段逻辑。结果是运行页为默认流程节点选择的 Skill 与 MCP 不进入提示词，也不起作用。同时，`workflow_activity_roles()` 只统计活动，默认流程的角色在这类查询中不出现。

## 决定

1. **调用 Agent 的步骤一律是活动。** `factory_default.yaml` 中项目经理起草、可测性、体验、界面、视觉、预算粗估、架构、预算正式版、开发、评审、测试、质量门禁、成本快照、交付汇总、收口、复盘改为 `kind: activity`，写明 `inputs` 与 `outputs`；提示词由编译器按通用活动拼装，含人类需求、附件、返工反馈、输入产物引用、Skill 与 MCP。
2. **系统节点只保留不调用 Agent 的步骤**：澄清检查、等待澄清、配置计划、范围、变更、回退升级。`HANDLERS` 相应缩减。
3. **活动新增 `instruction`。** 这一步特有的写作要求（例如「需求说明须含可检验的验收标准 AC-*」）写在流程文件里，追加到提示词。
4. **活动新增 `effect`，指向内置后处理**（`system_nodes.EFFECTS`，实现在 `default.py` 的 `EFFECTS`）。后处理只在 Agent 返回、按产物切分之后执行，负责原系统节点的判定与状态写入，不拼装提示词：
   - `developer`：返工次数加一、清空返工反馈、解析变更请求；另追加工作树范围与第几次开发两段提示。
   - `code_review`、`test_execute`、`qa_gate`：按结论块判定（Stub 沿用预设状态），写 `review_status`、`test_status`、`qa_status` 与失败反馈；测试另经验证命令核对，QA 另生成验收对照表。三者在提示词中附结论块要求。
   - `delivery`：缺少验收证据或 QA 未通过时不调用 Agent，直接写未交付结论。
   - `retro`：生成复盘打分、待批准提案、运行记录与成本台账。
   - `budget_rough`、`budget_final`、`cost_snapshot`：写 `budget_phase`。
5. **活动可以写 `routes` 与 `next`**，与系统节点相同；同一活动不能同时写 `returns_to`。默认流程的评审、测试、质量门禁、交付汇总沿用原来的条件去向（`failed:*`、`retries_exhausted`、`false:delivery_ready`），返工计数仍是 `dev_retry_count`。
6. **只写名称的输出可以不带模板**，前提是该名称在角色契约（`role.md` 的 `outputs`）中。这与不写 `outputs`、沿用角色契约时一致；以对象形式写的输出（流程页编辑出的格式）仍须有模板。一个活动有多项必需输出时，提示词要求每个产物写在以产物名为标题的二级标题下；切分时只以产物名标题分段。
7. **内置流程的活动受档案中 `skip_nodes` 裁剪**（`rail: builtin` 的流程），与原系统节点的 `skip_if_disabled` 行为一致。
8. **内置轨道标出格子种类。** 不调用 Agent 的格子 `kind` 为 `system`，运行页右栏不为这些格子显示模型、推理强度、Skill 与 MCP。
9. 含内置后处理或条件去向的流程，与含系统节点的流程一样不能当作子图插入，也不能放进并行支路。

## 后果

- 运行页为默认流程任一智能体步骤选择的 Skill 与 MCP，进入该步骤的提示词；其他步骤不受影响。
- 架构、测试、收口原先各调用两次 Agent，现在各调用一次，一次产出两项产物。提示词中的输入产物按产物名标注（例如 `requirement_spec：`），不再使用手写的中文标签。
- 默认流程的角色出现在 `workflow_activity_roles()` 中；被默认流程使用的角色按「已被流程引用」处理，不能删除。
- 测试与调试单独执行某一节点时，用 `default.run_builtin_node(节点标识, 状态)`，按流程文件中的定义执行，原来的同名函数不再存在。
- Skill 与 MCP 仍以提示词约束，后端没有按所选项过滤工具；需要硬约束时另行决定。
- 流程页编辑器保存时只保留它认识的字段，`handler`、`effect`、`instruction`、`routes`、`next`、`when` 不会带入副本；复制内置流程后在编辑器中保存会丢失这些字段。这是既有限制，需另行修复编辑器。
