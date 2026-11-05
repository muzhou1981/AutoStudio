# lark-cli 本地凭据（勿提交）

1. 复制 `api.txt.example` 为 `api.txt`，填入个人开发者应用的 App ID / App Secret。
2. 本机执行：`lark-cli config init --new --app-id <ID> --app-secret-stdin --brand feishu`（Secret 从 stdin 读入，见 ADR 0004）。
3. 用户身份：`lark-cli auth login --recommend`。
4. `api.txt` 与 `oauth-qrcode.png` 已在 `.gitignore` 中。

## 卡片回调（入站 HITL）

1. 开放平台启用 **事件订阅 → 回调配置**（长连接），订阅 `card.action.trigger`。
2. 本地消费并转发到 auto_studio（示例）：

```bash
lark-cli event consume card.action.trigger --as bot --timeout 30m \
  | while read -r line; do
      curl -sS -X POST http://127.0.0.1:8765/api/webhooks/feishu \
        -H 'Content-Type: application/json' \
        -d "$line" >/dev/null
    done
```

3. 无公网 URL 时可用联调接口：`POST /api/webhooks/feishu/card-action`。
