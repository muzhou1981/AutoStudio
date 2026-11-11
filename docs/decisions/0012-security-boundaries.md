# 0012 · 安全边界落在配置与入口，而不是提示词

- 状态：已实现
- 日期：2026-11-11
- 关联：[问题与改进方案](../plans/architecture-remediation.md) D7、D8；补充 [0004](0004-feishu-hitl-via-lark-cli.md) 的回调校验。

## 背景

「禁止推送、只改工作树」只写在角色提示词里，Cursor 后端保留 SDK 全部工具；Web 没有认证；HITL 请求体自报 `channel`；飞书 Webhook 令牌未配置时放行；审计不记录批复人。

## 决定

1. **推送防护。** 每个运行工作区启用 `extensions.worktreeConfig`，在本工作区的 `config.worktree` 中：
   - 把所有已有远端的 `pushurl` 设为不可用地址 `geni-studio-push-disabled:///`，`--no-verify` 也无法绕过；
   - 把 `core.hooksPath` 指向 git 目录下的防护钩子目录，`pre-push` 拒绝推送，其余钩子以符号链接指回原钩子目录，不改变提交钩子行为。
   当前分支模式下工作区即用户仓库，以持有标记登记；最后一个持有的运行进入完成、驳回或停止时撤销，删除运行时也会撤销。
2. **Web 访问令牌。** 设置 `GENI_STUDIO_WEB_TOKEN` 后，`/api/*`（飞书回调另有令牌）须带令牌（请求头、Bearer 或 Cookie）；首页以 `?token=` 写入仅限 HTTP 的 Cookie 后重定向。监听非回环地址（`GENI_STUDIO_WEB_HOST`）而未设置令牌时拒绝启动。
3. **审批人身份。** 审计行增加 `actor=`：Web 取 `GENI_STUDIO_WEB_OPERATOR`（缺省 `web`），飞书取消息发送者或卡片点击者的 `open_id`。`channel` 由服务端按入口确定。项目 `hitl.feishu.approvers` 非空时，名单外的飞书批复被拒绝，且不写入任何状态。
4. **回调默认校验。** 未配置 `GENI_STUDIO_FEISHU_WEBHOOK_TOKEN` 时拒绝回调（`url_verification` 除外）。内置事件桥在 Web 进程内启动时生成随机令牌并写入进程环境，桥接与服务端共用；独立桥接须显式配置令牌。仅本地调试可用 `GENI_STUDIO_FEISHU_WEBHOOK_INSECURE=1` 放行。
5. **验证命令。** 维持 D8 的做法：命令白名单、超时、密钥变量剔除与可选 `bwrap` 沙箱（见 `verification/command.py`）。

## 后果

- 运行期间当前分支模式的仓库不能推送，需要等本轮结束。
- 推送防护不覆盖「直接向 URL 推送且跳过钩子」（`git push --no-verify <url>`）；完整隔离需要进程级沙箱，留待后端支持。
- Web 令牌是单一共享令牌，`actor` 只区分到部署级别的操作者名；多用户身份需要接入单点登录，不在本决定范围内。
