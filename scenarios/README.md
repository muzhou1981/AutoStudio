# 场景配置（L1）

每个子目录对应一个 `scenario_key`，至少包含 `scenario.yaml`。可选：

- `workflow_profile.yaml`：与 `scenario.yaml` 深合并
- `templates/<artifact_name>.md`：覆盖 L0 默认模板

| scenario_key | 标题 | 设计轨 |
|---|---|---|
| `general_software` | 通用软件开发 | 开启 |
| `middleware` | middleware | 关闭，并跳过体验、界面、视觉 |
| `npu_operator` | NPU 算子开发 | 关闭，并跳过体验、界面、视觉 |
| `web_app` | Web 应用 | 开启 |

Run 输入示例：`{"scenario_key": "general_software", "human_request": "…"}`
