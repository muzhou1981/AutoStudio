# 0022 · 自举开发用独立端口预览，并以 Chrome DevTools MCP 验证界面

- 状态：已实现
- 日期：2026-11-12
- 关联：[0020](0020-role-session-per-run-and-cursor-settings.md)（加载项目与用户配置）；[0021](0021-run-process-lifecycle.md)（进程回收）。

## 背景

1. 自举开发时，角色改动的是正在驱动本轮的 GeniStudio 自身。Cursor IDE 中的内置浏览器是 IDE 提供的 MCP，经 SDK 创建的智能体无法使用；智能体工具集中没有浏览器类工具，只能读源码推断界面效果。
2. 若智能体为验证改动而重启 8765，会中断正在执行的这一轮。
3. 智能体的 Shell 继承主服务的环境：密钥、飞书通知对象，以及 `GENI_STUDIO_FEISHU_BRIDGE=1`。直接在工作树起服务会与主服务争抢飞书事件、发出通知；`.venv` 中以可编辑方式安装的包指向主仓库源码，不设 `PYTHONPATH` 时运行的并不是工作树中的改动。

## 决定

1. **浏览器 MCP 采用 Chrome DevTools MCP**，写入用户层 `~/.cursor/mcp.json`：`npx -y chrome-devtools-mcp@latest --headless --isolated --no-usage-statistics`，以绝对路径调用 nvm 中的 `npx`，并在 `env.PATH` 中补上 nvm 目录（服务进程的 PATH 不含 nvm）。无头、独立用户目录，不占用桌面，并行的智能体互不争用浏览器配置。配置页 Agent 一节随之列出。
2. **预览实例另起端口。** 新增 `scripts/preview.sh [端口]`（默认 8766，拒绝 8765）：以 `PYTHONPATH=<工作树>/src` 运行工作树源码，检查点放在工作树 `.geni_studio/preview/`，固定 stub 后端，关闭飞书事件消费，去掉密钥与通知对象。
3. **以项目规则告知角色。** `.cursor/rules/self-dev-preview.mdc`（始终生效）要求：不碰 8765，用脚本起预览，用 Chrome DevTools MCP 截图与读取 DOM 验证，改动后重启自己的预览。未改动 `roles/` 与 `workflows/default.py`。

## 后果

- 以真实 SDK 实测：智能体加载用户层配置后，经 `chrome-devtools` 完成打开页面、读取标题与截图。
- 预览实例、MCP 服务与无头 Chrome 都由这一轮的桥接派生，带有本轮标识，本轮结束时一并回收（ADR 0021）。
- 规则文件需提交到仓库，之后从基线分支创建的工作树才能带上；在此之前开始的 Run 看不到这条规则。
- 首次调用 `npx` 需要从 npm 源下载，依赖代理可用。
