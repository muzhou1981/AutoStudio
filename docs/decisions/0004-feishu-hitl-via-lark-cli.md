# 0004 · 飞书 HITL 经官方 lark-cli（个人开发者应用）

- 状态：已接受
- 日期：2026-11-05

## 背景

部分企业租户 **未开通飞书开放平台** 管理能力，无法在租户侧统一审批自建应用。开发者仍可用 **个人账号** 在 [飞书开放平台](https://open.feishu.cn/) 创建应用并开发调试。

auto_studio 一期飞书出站（PM 通知）需在此约束下可落地，且与 [ADR 0003](0003-pm-human-hitl-and-im-channels.md) 的 HITL API 语义一致。

## 决策

1. **默认后端**：`AUTO_STUDIO_LARK_BACKEND=lark_cli`（未显式配置且无 `LARK_APP_ID` 时默认 lark-cli）。
2. **出站消息**：通过 **`lark-cli im +messages-send --as bot`** 发送；App ID / Secret 由 **`lark-cli config init`** 写入本机 CLI 配置，**不要求** 写入 auto_studio 仓库 `.env`。
3. **备选后端**：`AUTO_STUDIO_LARK_BACKEND=env_bot` 时仍可读 `.env` 的 `LARK_APP_ID` / `LARK_APP_SECRET`（企业已开开放平台、希望进程内直连时使用）。
4. **项目绑定**：`projects/<id>/project.yaml` 的 `hitl.feishu.notify_chat_id` / `notify_open_id` 不变；Run 进入 `awaiting_human` 时发送文本通知 + Web 链接。
5. **入站（卡片/消息 → HITL）**：仍经 **HITL REST**；后续可用 `lark-cli event consume` 或 HTTP 回调适配，不在本 ADR 范围。
6. **与 lark-tools**：lark-tools 的 Cookie/`send` **不** 作为 PM 产品身份；lark-cli Bot 与 lark-tools `send-bot` 同为应用身份，auto_studio **产品路径首选 lark-cli** 以便与事件/卡片技能对齐。

## 配置步骤（开发者）

```bash
# 1. 个人账号创建应用，启用机器人，开通 IM 相关 scope
# 2. 本机初始化 CLI（按提示完成授权）
lark-cli config init --new

# 3. auto_studio
cp .env.example .env
# AUTO_STUDIO_LARK_BACKEND=lark_cli
# AUTO_STUDIO_PUBLIC_BASE_URL=http://127.0.0.1:8766

# 4. 项目 YAML（/config 可编辑）
# hitl.feishu.notify_chat_id: oc_xxx
```

Bot 须已加入目标群或允许单聊。

## 后果

- 部署 auto_studio 的机器须 **已安装 lark-cli 且 config 完成**；CI 无 CLI 时飞书通知自动跳过（仅 Web HITL）。
- 个人开发者应用受 **飞书开发者版可用范围** 限制，上线生产前须评估是否迁移至企业租户应用。

## 相关

- [ADR 0003](0003-pm-human-hitl-and-im-channels.md)
- [architecture.md](../architecture.md) 飞书配置节
