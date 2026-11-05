# 场景配置（L1）

每个子目录对应一个 `scenario_key`，至少包含 `scenario.yaml`。可选：

- `workflow_profile.yaml`：与 `scenario.yaml` 深合并
- `templates/<artifact_name>.md`：覆盖 L0 默认模板

Run 输入示例：`{"scenario_key": "npu_operator", "human_request": "…"}`
