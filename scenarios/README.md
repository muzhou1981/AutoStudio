# 场景配置（兼容层）

场景已降为兼容层（见 [ADR 0014](../docs/decisions/0014-workflow-profile.md)）。新项目在 `project.yaml` 的 `workflow.profile_id` 中直接选择流程，运行档案（`features`、`limits`、`gates`、`skip_nodes`、`verification`）写在流程文件的 `profile` 中。仍引用 `scenario_key` 的项目可以照常运行，配置预览会给出迁移提示；`migrate_to` 指明对应的流程。

每个子目录对应一个 `scenario_key`，至少包含 `scenario.yaml`。可选：

- `workflow_profile.yaml`：与 `scenario.yaml` 深合并
- `templates/<artifact_name>.md`：覆盖 L0 默认模板

| scenario_key | 标题 | 设计轨 | 对应流程 |
|---|---|---|---|
| `general_software` | 通用软件开发 | 开启 | `factory_default` |
| `middleware` | middleware | 关闭，并跳过体验、界面、视觉 | `factory_default` |
| `npu_operator` | NPU 算子开发 | 关闭，并跳过体验、界面、视觉 | `npu_operator_dev` |
| `self_improve` | 用工厂改进 GeniStudio 自身 | 关闭 | `self_improve` |
| `web_app` | Web 应用 | 开启 | `factory_default` |

Run 输入示例：`{"scenario_key": "general_software", "human_request": "…"}`
