# 同类 Agent 任务编排的 Web 界面调研

- 日期：2026-11-06
- 对照需求：[需求第 15 条](../requirements.md)「工厂状态透明：Web 可实时查看当前流程所在节点，飞书可通过消息查询」
- 性质：检索结论，不是已接受的技术决策

## 1. 目的

工厂流程是预先写好的 LangGraph，节点名单已知。人需要在 Web 上看到这一轮走到哪，也要能在飞书里用一句话问到同一份状态。本文检索大厂与同类产品的任务界面，标出值得借鉴的交互，以及不适合照搬的部分。

检索日为 2026-11-06。材料来自各产品公开文档、更新说明与官方仓库，未逐一点击其登录后的生产界面。

## 2. 本仓库现状

人工处理页右侧已有阶段和「下一节点」，需要手动刷新。节点是一行文字，看不出哪些已经走过、哪些被场景裁掉、当前是在等人工还是在执行某个角色。飞书入站处理批准、驳回、澄清答复和升级选择；询问「现在到哪了」不会得到状态回复。

因此第 15 条尚未满足：缺实时的节点位置，也缺飞书上的只读查询。

## 3. 检索范围

| 类别 | 产品 | 为什么看 |
|------|------|----------|
| 图编排 | LangSmith Studio | 本工厂使用 LangGraph，Studio 是同栈的调试界面 |
| 代码代理 | GitHub Copilot coding agent、OpenAI Codex、Google Jules、Cursor Cloud Agents、Devin | 云端长任务的进度、日志与交付物 |
| 多角色 | Microsoft AutoGen Studio | 多 Agent 消息流与成本可视化 |
| 开源参照 | OpenHands | 开源界面里较完整的实时活动流 |
| 即时通信 | Slack 上的会话状态与 `status` 类命令 | 对照「飞书用消息查询」 |

## 4. 各产品观察到的界面

### 4.1 LangSmith Studio

Studio 分图模式与对话模式。图模式展示图结构、走过的节点、中间状态，并可对线程做分叉。运行前可用表单填写输入，也可以切到原始 JSON。执行中可以在指定节点之前或之后打断点，暂停后查看状态再继续。时间旅行可以从旧检查点重放，或改状态后分出一条新运行；打断点在重放时会再次触发。

来源：

- [LangSmith Studio](https://docs.langchain.com/langsmith/studio)
- [How to use Studio](https://docs.langchain.com/langsmith/use-studio)
- [Use time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)

### 4.2 GitHub Copilot coding agent

GitHub 在仓库内提供 Agents 页，会话与代码、拉取请求、议题放在一起。点进一次会话可看日志、令牌用量和时长。日志把同类工具调用收成一组，工具输出可内联预览，文件变更用差异视图。提交说明链回这次会话，便于审查时追溯。运行中可以追加指令纠偏，不必先停掉会话。

来源：

- [Managing agent sessions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents)
- [仓库中的 Agents 页](https://github.blog/changelog/2026-01-26-introducing-the-agents-tab-in-your-repository/)

### 4.3 OpenAI Codex

Codex 在云端隔离环境里执行任务。Web、桌面、移动端、GitHub 评论、Slack 与 Linear 都能发起，完成后给出摘要、差异和日志。任务可以并行，人离开页面后任务继续。公开讨论里有人要求每个任务显示自动百分比；维护侧的顾虑是，开放式任务无法可靠估计剩余工作。较稳妥的做法是只统计事先声明的清单完成数，没有清单就不显示百分比。

来源：

- [Using Codex Cloud](https://help.openai.com/en/articles/20001545-using-codex-cloud)
- [Codex 进度百分比讨论](https://github.com/openai/codex/issues/35930)

### 4.4 Google Jules

计划批准之后才开始改代码。工作过程是一条活动流：每一步的说明、输出或错误、以及行内差异。人可以在中途用对话要求改做法。结束时给出变更文件、耗时、增删行数、分支名和提交说明，并可直接发布分支或拉取请求。

来源：

- [Running Tasks with Jules](https://jules.google/docs/running-tasks/)
- [Reviewing code changes](https://jules.google/docs/code/)

### 4.5 Devin

会话里用进度步骤串起命令、代码修改和浏览器操作。点某一步，活动流只留下这一步的记录。2026 年 10 月的更新把进度与终端并成一个活动视图，支持搜索、按类型过滤，以及可固定的详情抽屉。另有会话洞察：按时间标出阻碍、关键事件和产出，并给出改写后的提示词。会话也提供网页里的编辑器和桌面，供人接管。

来源：

- [Devin Session Tools](https://docs.devin.ai/work-with-devin/devin-session-tools)
- [Session Insights](https://docs.devin.ai/product-guides/session-insights)

### 4.6 Cursor Cloud Agents

云端代理在自己的环境里安装依赖、跑测试，并留下录像、截图或日志作为验证材料。Web、桌面与 iOS 看的是同一条运行。人可以看实时记录、给正在跑的代理追加指令、点开子代理记录，并在同一处审阅差异与拉取请求。一轮结束会有推送通知。代理评论可以链回这次运行。

来源：

- [Cloud Agents capabilities](https://cursor.com/docs/cloud-agent/capabilities)
- [Cursor for iOS](https://cursor.com/docs/cloud-agent/mobile)
- [Cloud Agents release notes](https://cursor.com/docs/release-notes/cloud-agents)

### 4.7 Microsoft AutoGen Studio

游乐场在团队运行时流式显示各 Agent 的消息，右侧用控制转移图表示消息走向，并带令牌用量。可以暂停或停止。构建视图用声明式配置或拖拽组装团队、模型和工具。事后剖析统计消息数、费用、工具调用次数和成败。

来源：

- [AutoGen Studio 用户指南](https://microsoft.github.io/autogen/stable/user-guide/autogenstudio-user-guide/)

### 4.8 OpenHands

对话里用一块状态标签写明当前动作，例如正在思考或正在执行某条工具。连续的工具调用折叠成「已完成若干动作」。断线后重连，历史和进行中的运行还在。流式增量只用于当场绘制，不写入持久记录；重连后看到的是最终消息。

来源：

- [OpenHands 活动流特性说明](https://enyst.github.io/openhands-features/F06-agent-activity.html)

### 4.9 即时通信里的状态查询

Slack 官方的代码频道可以给会话设置状态（例如处理中），并用上下文条显示仓库、分支和拉取请求链接。社区里的 Claude Code 桥接提供明确的 `status` 命令，回复当前任务，而不是把终端全部贴出。Nimbus 在任务线程里按阶段打勾：索引、计划、实现、验证，完成时附上拉取请求地址。

来源：

- [Slack Code](https://docs.slack.dev/ai/slack-code/)
- [claude-slack-bridge](https://github.com/nariakiiwatani/claude-slack-bridge)
- [Nimbus 的 Slack 进度](https://docs.get-nimbus.com/integrations/slack)

## 5. 与工厂的对照

| 观察到的做法 | 对 auto_studio 的含义 |
|--------------|------------------------|
| 图上标出当前节点、已执行路径和剩余路径 | 最贴近第 15 条。节点名单已知，可以用轨道表示已完成、进行中、等待人工、被场景跳过、尚未到达 |
| 输入用表单，JSON 放在旁边 | 配置页已经按这个方向拆过。状态页同样把摘要放前面，原始状态放进折叠入口 |
| 会话列表与仓库放在一起，日志按工具调用分组 | 左侧应能切换多次 Run。活动按工厂节点分组，不铺开模型原文 |
| 先批准计划，再按步骤更新活动流；结束时给出文件、耗时和分支 | 与需求确认、架构评审两道关卡同构。结束摘要应对验收证据 |
| 点一个步骤，只看这一步的命令和改动 | 右侧检视跟随当前节点，显示该节点的产物与测试输出 |
| 输入框旁一块小标签写「正在做什么」；断线后历史仍在 | 状态要自动更新。重连后仍绑定同一个 `thread_id` |
| 即时通信用固定格式回答：阶段、当前步骤、在等谁、链接 | 飞书查询回一张短卡片。长说明仍打开 Web |
| 验证材料（测试日志、截图、录像）和运行放在一起 | 与「无证据不视为交付」一致。节点旁挂测试输出和 QA 结论 |
| 消息流上标注各角色成本 | 已有成本账本，可以挂到对应节点 |
| 没有事先清单就不显示完成百分比 | 工厂有节点清单，可以显示「本轮要走的节点里完成了几个」。没有清单时只写节点名 |
| 从旧检查点改状态再分叉 | LangGraph 做得到，但会和基线、变更控制冲突。调研阶段不建议放进工厂界面 |
| 在网页里接管编辑器或浏览器 | 超出工厂控制台的范围。代码仍在目标工作树里看 |
| 拖拽组装 Agent 团队 | 角色已由 `roles/<name>/role.md` 定义，不在 Web 上重组 |

## 6. 建议的第一块

只覆盖第 15 条，不扩大成调试器或网页 IDE。

Web：一条竖向节点轨道。状态分五类：已完成、进行中、等待人工、被场景跳过、尚未到达。当前节点来自现有运行状态里的下一节点与阶段。轨道旁边保留现在的检视摘要。更新先轮询已有状态接口；节点多、刷新显眼时再改为服务端推送。

飞书：识别「状态」「到哪了」「status」一类问法。回复固定四行：阶段、当前节点、是否在等人工及待办类型、Web 链接。这条查询不执行批准或驳回。

百分比仅在「本轮实际会执行的节点」可数时显示，分母排除被场景跳过的节点。

界面设计见 [UI/UX 设计说明](../design/ui-ux.md)。
