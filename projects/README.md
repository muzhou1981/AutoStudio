# 项目配置（L2）

每个子目录对应一个 `project_id`，至少包含 `project.yaml`。可通过 `scenario_key` 绑定场景；`workflow` / `artifacts` 字段覆盖场景默认值。

Run 输入示例：`{"project_id": "_example", "human_request": "…"}`（未传 `scenario_key` 时从项目文件读取）。
