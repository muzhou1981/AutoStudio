# 0023 · 按角色为本轮选择 Fast 模式

- 状态：已实现
- 日期：2026-11-12
- 关联：[0020](0020-role-session-per-run-and-cursor-settings.md)（角色会话与 Cursor 设置）。

## 背景

1. Cursor SDK 后端下角色执行较慢。Cursor 模型目录（`Cursor.models.list`）中多数模型声明了 `fast` 参数（取值 `true`/`false`），默认值因模型而异：`composer-2.5`、`grok-4.7` 默认开启，`claude-opus-5-5`、`gpt-5.6-sol` 默认关闭。此前只传推理强度参数，无法显式开启 Fast。
2. Codex SDK（`openai_codex`）在 `thread_start`、`thread_resume`、`Thread.turn` 上提供 `service_tier`，`"fast"` 为 Fast 档，`"default"` 为标准速度；模型目录以 `service_tiers`（旧版为 `additional_speed_tiers`）声明是否支持。
3. Fast 模式按更高费率计费，不宜一律开启。

## 决定

1. **按角色、按轮选择，三态。** 运行页右栏「角色属性」中与模型、推理强度并排新增「Fast」：「模型默认」不传参数；「开」「关」显式指定。只在模型目录声明支持时可选；Auto 模型或不支持的模型指定开或关时，启动与保存均拒绝。
2. **随 Run 保存。** 图状态 `FactoryState` 新增 `role_fast_modes: dict[str, str]`（值为 `on` 或 `off`），草稿、启动、运行中修改（`PUT /api/runs/{id}/role-models` 的 `role_fast_modes`）与复制 Run 均携带；执行时经上下文变量交给后端，与推理强度相同。
3. **后端映射。** Cursor：在 `ModelSelection.params` 中追加 `fast=true/false`，调用前对照模型目录校验。Codex：本轮调用传 `service_tier="fast"` 或 `"default"`。Fast 设置进入会话标识，改动后从该角色下一次调用起换用新会话。
4. 本轮不提供项目 YAML 与工厂级的 Fast 默认值，需要时再加。

## 后果

- 右栏角色组由两项变为三项，两组改为不均分：角色组约占 2.6 份，步骤组（只有 Skill）约占 1 份。
- 本机未安装 `openai_codex`，Codex 的 Fast 映射只有在安装 SDK 后才由契约测试（签名绑定）校验。
