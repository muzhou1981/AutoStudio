# lark-cli 本地凭据（勿提交）

1. 复制 `api.txt.example` 为 `api.txt`，填入个人开发者应用的 App ID / App Secret。
2. 本机执行：`lark-cli config init --new --app-id <ID> --app-secret-stdin --brand feishu`（Secret 从 stdin 读入，见 ADR 0004）。
3. 用户身份：`lark-cli auth login --recommend`。
4. `api.txt` 与 `oauth-qrcode.png` 已在 `.gitignore` 中。

## 卡片回调（入站 HITL）

1. 开放平台启用 **事件订阅 → 回调配置**（长连接），订阅 `card.action.trigger`。
2. 本地消费并转发到 AutoStudio（推荐内置桥接）：

```bash
auto-studio-web   # 另开终端
auto-studio-feishu-bridge --webhook http://127.0.0.1:8765/api/webhooks/feishu
# 默认同时转发 card.action.trigger 与 im.message.receive_v1（PM 澄清文本答复）
```

等价 shell 管道见 ADR 0004；环境变量 `AUTO_STUDIO_FEISHU_WEBHOOK` 可覆盖默认 URL。

3. 无公网 URL 时可用联调接口：`POST /api/webhooks/feishu/card-action`。
