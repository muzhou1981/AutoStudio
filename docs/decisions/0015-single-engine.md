# 0015 · 单一引擎：内置流程也由流程文件编译

- 状态：已实现
- 日期：2026-11-11
- 关联：[问题与改进方案](../plans/architecture-remediation.md) D1；取代 [0005](0005-selected-workflow-compiles-run-graph.md) 中「内置流程保留 `default.py` 手写图」的兼容安排。

## 背景

`workflows/factory_default/workflow.yaml` 标记 `engine: default`，`uses_default_engine()` 据此改走 `default.py` 中手写的节点与边，流程文件只用于展示。自定义流程走编译器。两条路径在关卡、回退、变更控制和澄清上各自演进，复制内置流程得到的是另一套行为。

## 决定

1. 编译器增加系统节点 `kind: system`（后由 [0019](0019-default-flow-agent-steps-as-activities.md) 限定为不调用 Agent 的步骤）：`handler` 引用内置实现（`workflows/system_nodes.py` 的 `HANDLERS`，实现在 `default.py`，调用时按名称查找）；`routes` 按顺序声明条件去向，都不满足时去往 `next` 或文件中的下一个节点；系统节点不写 `returns_to`。
2. 系统节点和活动都可以写 `when`，条件不成立时该节点不执行、直接通过。条件词表：`feature:design_track`、`feature:finance`、`pending:<类型>`、`impact:<影响>`、`failed:<状态字段>`、`false:<字段>`、`retries_exhausted`，`not:` 取反，列表表示同时成立。保存流程时校验处理函数、条件与去向。
3. `factory_default.yaml` 写出完整的节点、可选分支与路由，删除 `engine: default` 与 `uses_default_engine()`。`default.py` 只保留图状态、节点实现与编译入口：`compile_graph()` 编译内置流程文件，供 `langgraph.json` 与未选流程的轮次使用。
4. 项目选择 `factory_default` 时与其他流程一样经 `compile_for_project` 编译，并冻结 `workflow_definition_ref`。该流程声明 `rail: builtin`，进度轨道沿用内置轨道（标签、设计轨与财务的隐藏规则），因此不写入 `workflow_nodes`。
5. 含系统节点的流程不能当作子图插入（路由按节点标识书写，展开时不重写）。没有 `workflow_id` 的历史检查点仍使用默认图；节点标识未变，可以继续执行。

## 后果

- 运行图只有一条生成路径；修改 `factory_default.yaml` 的副本（例如删除可测性评审）直接改变运行行为。
- 默认流程的智能体节点起初仍以系统节点形式复用原实现；已由 [0019](0019-default-flow-agent-steps-as-activities.md) 改为通用活动，判定与状态写入改由活动的内置后处理完成。
- 复制出的流程保留 `rail: builtin` 时，轨道仍按内置节点表显示；删除节点后轨道中的对应项不会消失，需要去掉该字段改用流程节点表。
