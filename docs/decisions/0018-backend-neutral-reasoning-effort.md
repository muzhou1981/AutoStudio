# 0018 · 推理强度与后端解耦，Cursor 以模型参数传递

- 状态：已实现
- 日期：2026-11-11
- 关联：[0009](0009-runtime-correctness.md) §6.6、§6.10（Codex 推理强度）；[ui-ux §13.7](../design/ui-ux.md)。

## 背景

角色推理强度最初只为 Codex 接通：取值校验、按角色合并的函数放在 `backends/codex_settings.py`，模型目录只为 Codex 提供推理级别，运行页的「角色模型与推理强度」在 Cursor 后端下仍按 Codex 逻辑渲染，所选级别也不会传给 Cursor SDK。该设置放在运行页中栏，与同属角色配置的 Skill 和 MCP（右栏）分处两处。

Cursor SDK 的 `Cursor.models.list` 为每个模型列出 `parameters`，推理参数名因模型而异（`effort`、`reasoning_effort` 或 `reasoning`），默认值见 `is_default` 的 `variants`；创建 Agent 时以 `ModelSelection(id, params=(ModelParameterValue(id, value),))` 指定。

## 决定

1. **通用部分移出 Codex 模块。** 级别集合、取值规范化、按角色合并与校验移到 `backends/reasoning.py`；`codex_settings.py` 只保留 Codex 工厂级设置。
2. **模型目录。** Cursor 模型行增加 `reasoning_param`、`reasoning_efforts` 与 `default_reasoning_effort`，目录缓存 600 秒。
3. **调用。** `runner.effort_for_role` 按「本轮角色选择、项目 YAML、空」得出级别；Cursor 后端有级别时以 `ModelSelection` 传入该模型的推理参数，无级别时仍传模型字符串。Auto 模型或目录未声明该级别时报错，不静默降级。工厂级推理设置仍只对 Codex 生效。
4. **界面。** 模型与推理强度拆成两个独立选择，移到右栏该节点的 Skill 和 MCP 之上，按角色生效；中栏列表删除。

## 后果

- Cursor 角色的推理强度真正生效；以 `grok-4.7` 实测，low 与 high 的推理 token 分别为 25 与 538。
- 选定级别时须能读取模型目录；目录不可读时该节点调用失败并给出原因，未选级别的角色不受影响。
- 目录列出的部分模型可能因账号地区不可用，选择与否由使用者判断，页面不另行过滤。
