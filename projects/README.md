# 项目配置（L2）

每个子目录对应一个 `project_id`，至少包含 `project.yaml`。在 `workflow.profile_id` 中选择流程；`workflow` / `artifacts` 字段覆盖流程 `profile` 的默认值。合并顺序为“单次 Run > 项目 > 场景（兼容层）> 流程 profile”。`scenario_key` 仅为旧项目保留。

在 Web“项目”页或通过目录创建的项目目录为**本地数据**，默认由 `.gitignore` 忽略（仓库中仅跟踪 `_example/`）。需要把某一项目纳入版本库时，在 `.gitignore` 中对该 `project_id` 增加例外规则。

Run 输入示例：`{"project_id": "_example", "human_request": "…"}`（未传 `scenario_key` 时从项目文件读取）。
