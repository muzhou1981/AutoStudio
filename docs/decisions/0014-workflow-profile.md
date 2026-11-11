# 0014 · 运行档案并入流程，场景降为兼容层

- 状态：已实现
- 日期：2026-11-11
- 关联：[问题与改进方案](../plans/architecture-remediation.md) D6；修订 [0002](0002-scenario-project-config-and-cropping.md) 的合并层级。

## 背景

需求 §1.1 已决定「场景收进流程」，但 `scenarios/*/scenario.yaml` 仍承载 `features`、`limits`、`gates`、`skip_nodes`，并以 `profile_id: *_v1` 指向并不存在的流程（例如 `npu_operator_v1` 与流程 `npu_operator_dev` 不对应）。新建项目的默认文本也绑定 `npu_operator` 场景。

## 决定

1. 流程文件可声明 `profile`，其中 `features`、`gates` 为开关，`limits` 为非负整数，`skip_nodes` 为节点列表，`verification` 与项目中的写法相同。保存流程时校验这些类型，未知项拒绝保存。
2. 配置合并顺序为「单次 Run（状态中的覆盖项）> 项目 > 场景（兼容层）> 所选流程的 `profile`」。所选流程只由 `workflow.profile_id` 决定，且必须是已有流程；否则不合并档案，并在配置预览的 `notices` 中提示。
3. 场景保留为只读兼容层：项目仍引用 `scenario_key` 时照常读取，并在 `notices` 中给出迁移提示。内置场景删除不对应的 `profile_id`，以 `migrate_to` 指明对应流程（`npu_operator` → `npu_operator_dev`，`self_improve` → `self_improve`，其余 → `factory_default`）。场景排在流程之上，使旧项目的行为不变。
4. 内置流程 `factory_default`、`npu_operator_dev`、`self_improve` 补齐原场景中的档案字段；新建项目的默认文本改为 `workflow.profile_id: factory_default`，不再写 `scenario_key`。

## 后果

- 新项目只需要选择流程；档案字段集中在流程文件中，随流程复制。
- 旧项目可以继续运行，迁移是可选的；删除 `scenario_key` 后行为只由流程与项目决定。
- 场景目录下的 `templates/` 模板查找仍保留，待产物模板也迁入流程后再移除场景目录。
