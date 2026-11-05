# lark-cli 本地凭据（勿提交）

1. 复制 `api.txt.example` 为 `api.txt`，填入个人开发者应用的 App ID / App Secret。
2. 本机执行：`lark-cli config init --new --app-id <ID> --app-secret-stdin --brand feishu`（Secret 从 stdin 读入，见 ADR 0004）。
3. 用户身份：`lark-cli auth login --recommend`。
4. `api.txt` 与 `oauth-qrcode.png` 已在 `.gitignore` 中。
