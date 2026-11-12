# GeniStudio 问题与改进方案

- 日期：2026-11-11
- 代码基线：`3475c35`（分支 `opt/architecture-review` 自此分出）
- 来源：系统架构评审。评审结论另见幻灯片《GeniStudio 架构评审》，本文是独立、可执行的整改依据。
- 适用范围：`src/geni_studio/`、`workflows/`、`scenarios/`、`tests/`、`docs/`。

本文每一项按「现象与证据 → 根因 → 改进方案 → 验收标准 → 落地状态」组织。方案层面问题编号 `D1`–`D8`，代码层面问题编号 `C1`–`C14`。多项问题共用同一处改造时，在各自条目中互相引用，不重复描述。

> 关于 `default.py`：`AGENTS.md` 规定 `src/geni_studio/workflows/default.py` 由人工编写，未经明确要求不得改写。本轮整改由项目负责人明确要求「根据评审发现的方案和代码问题逐项落地」，其中 C1–C3 与 D1 的证据直接位于该文件，因此本轮对其做了必要修改，修改范围在对应条目中逐条列明。

## 总览

| 编号 | 问题 | 级别 | 落地状态 |
|------|------|------|----------|
| D1 | 默认引擎与流程编译器两套实现、两份真相 | 高 | 已落地 |
| D2 | 产物是无结构字符串，控制流依赖正则与文本约定 | 高 | 已落地 |
| D3 | 产物词表写死在 `FactoryState` 中 | 中 | 已落地 |
| D4 | 运行时与 Web 进程耦合，HITL 请求同步跑图 | 高 | 已落地 |
| D5 | 工作树隔离与项目级写锁相互抵消，并行支路不能写 | 中 | 已落地 |
| D6 | 场景与流程两套配置并存 | 中 | 已落地 |
| D7 | 安全边界依赖提示词，审批无身份 | 高 | 已落地 |
| D8 | 验证命令与核心场景不匹配，且不隔离密钥 | 高 | 已落地 |
| C1 | 默认图代码评审永远通过 | 高 | 已落地 |
| C2 | 返工时程序员看不到评审、测试、QA 结论 | 高 | 已落地 |
| C3 | 变更控制分支不可达 | 高 | 已落地 |
| C4 | Cursor 后端每次调用新建实例，会话不能续接 | 高 | 已落地 |
| C5 | 飞书 Webhook 在 async 路由中同步跑图 | 高 | 已落地 |
| C6 | 读接口写检查点；SSE 每连接占线程 | 中 | 已落地 |
| C7 | 列表与起名全表扫描检查点；缓存无界 | 中 | 已落地 |
| C8 | 角色正文与流程定义写入每个检查点 | 中 | 已落地 |
| C9 | 写锁文件追加 PID 不截断，探测与加锁有竞态 | 中 | 已落地 |
| C10 | 工作树与分支只建不删 | 中 | 已落地 |
| C11 | 会话查看依赖静态节点表，且按角色归档 | 中 | 已落地 |
| C12 | 角色能力声明三处来源 | 低 | 已落地 |
| C13 | `GraphRunService` 与 `hitl.html` 过大；状态码靠错误文本匹配 | 低 | 已落地 |
| C14 | 导入即产生副作用；测试读取开发机 `.env` | 低 | 已落地 |

## 实施顺序

1. **第一批：正确性止血**——C1、C2、C3（连同 D2 的结构化结论部分）、C4、C9、C14、D8。
2. **第二批：运行时**——D4、C5、C6、C7。引入持久化任务表与执行器，HTTP 与飞书入口只写决定、入队、立即返回。
3. **第三批：存储与治理**——C8、C10、C11、C12、D7。
4. **第四批：架构收敛**——D1、D3、D2（产物引用与全文传递）、D6、D5。
5. **第五批：可维护性**——C13。

每一项完成后运行 `pytest` 与 `ruff check`，并在本文「落地状态」与「落地记录」中写明提交与验证证据。

---

## 方案层面

### D1 两套引擎、两份真相

**现象与证据。** 内置流程 `workflows/factory_default/workflow.yaml` 标记 `engine: default`，`config/workflow_defs.py` 的 `uses_default_engine()` 据此改走 850 行硬编码的 `workflows/default.py`；该 YAML 的节点只用于展示。自定义流程走 `workflows/executable.py`。两者在回退判定（预设状态与 `STATUS: fail`）、验收对照、变更控制、PM 澄清上的行为不同。

**根因。** ADR 0005 为兼容既有默认图保留了 `default.py`，此后新特性只加在编译器上，默认图独立演进。

**改进方案。**
1. 在编译器中增加「系统节点」（`kind: system`），把默认图中不调用 Agent 或带特殊路由的逻辑做成可复用节点：`pm_clarification`（PM 澄清）、`change_control`（变更控制）、`acceptance`（验收对照与交付判定）、`config_plan`（配置计划）。
2. 活动节点支持 `when` 条件（`feature:design_track`、`feature:finance`），以覆盖默认图的可选分支。
3. 把 `factory_default.yaml` 改写为完整、可编译的流程，删除 `engine: default` 分支；`default.py` 保留为该流程的编译入口（供 `langgraph.json` 与 LangGraph Studio 使用），不再手写节点与边。
4. 旧检查点（无 `workflow_definition`）仍按历史规则只读查看。

**验收标准。** 任一运行都经编译器生成；`uses_default_engine` 不再存在；原默认图的测试场景（关卡、澄清、回退升级、变更回关卡、验收对照、财务与设计链开关）在编译后的 `factory_default` 上全部通过。

### D2 产物是无结构字符串，控制流依赖正则

**现象与证据。** `FactoryState` 的产物均为 `str`；上游产物以 `[:8000]` 截断后拼入提示词；结论依赖 `AC-\d+` 出现与否（`verification/acceptance.py`）、`STATUS: fail`（`executable.py:21`）、`IMPACT:`、`## 待澄清`。模型在报告中写出编号即视为覆盖。

**根因。** 第一版以「先跑通」为目标，节点输出直接作为状态值，没有定义机器可读的结论格式。

**改进方案。**
1. **结构化结论（verdict）。** 需要判定的活动在正文末尾输出一个 `verdict` 围栏块（JSON）：`status`（`pass`/`fail`）、`ac`（每个验收编号的 `pass`/`fail`/`untested`）、`impact`（`none`/`scope`/`architecture`）、`summary`。解析器 `verification/verdict.py` 负责提取与校验。真实后端缺少或无法解析时按失败处理（失败即关闭）；Stub 后端沿用预设状态，便于在 Studio 中调试分支。
2. **验收对照改为按结论判定。** 一个验收编号视为通过，需满足其一：QA 结论中该编号为 `pass`；或验证命令退出码为 0 且其输出含该编号。仅在正文中「出现」不再算覆盖。
3. **产物引用与全文传递。** 每个产物落盘到运行目录（`.geni_studio/runs/<thread>/artifacts/<name>.md`），并记录元数据（产出节点、尝试次数、摘要哈希）到 `artifact_meta`。提示词对具备文件读取能力的后端给出产物路径与摘要，不再按字符截断；Stub 后端仍内联正文。

**验收标准。** 评审、测试、QA、编译器回退均由结论块驱动；单元测试覆盖「只写编号不给结论」不再通过；提示词中不再出现硬编码截断；`artifact_meta` 随运行写入。

### D3 产物词表写死

**现象与证据。** `executable.py:28-40` 拒绝任何不在 `FactoryState.__annotations__` 中的产物名，新增产物须改 Python。

**改进方案。** 增加 `extra_artifacts: dict[str, str]`（合并式通道）。编译器允许流程声明新的产物名，只要满足「名称合法（小写字母、数字、下划线）且有模板或显式声明」；读写时，已知产物走原字段，其余走 `extra_artifacts`。产物持久化、产物查看接口与轨道同步支持新产物。

**验收标准。** 一份声明自定义产物 `kernel_spec` 的流程可以编译、运行、在运行目录落盘并通过接口查看。

### D4 运行时与 Web 进程耦合

**现象与证据。** `enqueue_start` 在 Web 进程内起守护线程；`submit_hitl`、`resume`、`continue_interrupted` 同步调用 `graph.invoke` 直到下一个关卡；停止、暂停标记在 `hitl/control.py` 的内存集合中；进程重启后靠「被查看时」惰性标记中断。

**改进方案。**
1. 新增 `runtime/store.py`：SQLite 任务表（`run_jobs`：`thread_id`、`kind`、`payload`、`state`、`attempts`、时间戳），以及运行控制表（`run_controls`：停止、暂停请求），位于检查点同目录的 `runtime.sqlite`。
2. 新增 `runtime/executor.py`：执行器从任务表领取任务（同一轮串行），在线程池中执行；默认随 Web 进程启动，也可通过 `geni-studio-worker` 独立进程运行（设置 `GENI_STUDIO_EXECUTOR=external` 时 Web 不启动内置执行器）。
3. 所有入口（启动、HITL 提交、继续、续跑、飞书回调）只做校验、写入决定、入队，立即返回当前状态。
4. 进程启动时恢复：处于 `running` 但没有活动任务的轮次标记为 `interrupted`；未完成的任务重新入队或标记失败。

**验收标准。** HITL 提交接口在图仍需执行时于毫秒级返回 `running`；外部执行进程模式可用；停止请求跨进程生效；重启恢复有测试覆盖。

### D5 隔离设计与锁粒度相互抵消

**现象与证据。** 每轮已有独立工作树，但 `workspace/policy.py` 的写锁以目标仓库为粒度，同项目多轮串行；并行支路因「工作区未隔离」被 `executable.py:134-141` 拒绝写入与执行命令。

**改进方案。**
1. 写锁降到「可写目录」粒度：独立工作树模式锁该工作树；当前分支模式锁仓库根。
2. 并行支路含写入或命令角色时，在汇合前为每条支路从本轮工作树的当前内容创建快照工作树（`git stash create` 生成快照提交，不改动本轮工作树），支路 Agent 在各自工作树执行；汇合时把各支路相对快照的差异依次以三方合并方式应用回本轮工作树，冲突时升级给人，并写入冲突说明。

**验收标准。** 同一项目两轮可以同时运行；含程序员角色的并行支路可以执行，并在汇合后把两路改动合入本轮工作树；冲突场景有测试。

### D6 场景与流程两套配置并存

**现象与证据。** 需求 §1.1 已决定「场景收进流程」，但 `scenarios/*/scenario.yaml` 的 `skip_nodes`、`features`、`limits` 仍作用于默认图；`npu_operator` 场景的 `profile_id: npu_operator_v1` 与流程 `npu_operator_dev` 不对应。

**改进方案。** 流程文件承载运行档案（`profile`：`features`、`limits`、`gates`、`verification`），配置合并改为「单次 Run > 项目 > 流程 > 工厂默认」。场景文件降为只读兼容层：仅在项目仍引用 `scenario_key` 时读取并给出迁移提示；内置流程补齐原场景中的档案字段；修正 `npu_operator` 的不对应。

**验收标准。** 新建项目不再需要场景；流程中的 `features.design_track`、`limits.max_dev_retries` 生效；旧项目引用场景时仍可运行并在配置预览中提示迁移。

### D7 安全边界依赖提示词

**现象与证据。** Cursor 后端保留 SDK 全部默认工具，「禁止推送、只改工作树」只写在提示词里；`reject_remote_push` 只作用于工厂自己执行的验证命令；Web 无认证；HITL 的 `channel` 由请求体自报；飞书 Webhook 令牌未配置时放行；审计不记录审批人。

**改进方案。**
1. **推送防护落到 git 配置。** 为每个运行工作树启用工作树级配置，把所有远端的 `pushurl` 设为不可用地址，并安装拒绝推送的 `pre-push` 钩子；当前分支模式同样设置，交付后恢复。
2. **Web 访问令牌。** 设置 `GENI_STUDIO_WEB_TOKEN` 后，所有 `/api/*` 请求须携带令牌（请求头或 Cookie）；监听地址不是回环地址时强制要求设置。
3. **审批人身份。** HITL 审计记录 `actor`：Web 取访问令牌对应的操作者名（`GENI_STUDIO_WEB_OPERATOR`，缺省 `web`），飞书取发送者 `open_id`。项目可配置 `hitl.feishu.approvers`（`open_id` 列表），配置后非名单成员的飞书批复被拒绝。`channel` 由服务端按入口确定，不再信任请求体。
4. **Webhook 默认校验。** 内置事件桥启动时生成随机令牌并同时传给桥与服务端；外部桥必须显式配置令牌，未配置时拒绝回调。

**验收标准。** 工作树内 `git push` 失败；未带令牌访问 API 返回 401；非名单 `open_id` 批复被拒；审计行含 `actor=`；未配置令牌的外部回调被拒绝。

### D8 验证命令与核心场景不匹配

**现象与证据。** `verification/command.py` 白名单为 `pytest`、`python`、`python3`、`go`、`cargo`、`npm`，超时固定 120 秒；NPU 与 C++ 常用的 `make`、`cmake`、`ctest`、`bash` 脚本无法执行；子进程继承 `CURSOR_API_KEY`、`OPENAI_API_KEY` 等密钥。

**根因。** 白名单与超时为 Python 试点场景写死。

**改进方案。** 项目或流程中的 `verification` 支持：`command`（字符串或参数列表）、`allow`（追加允许的可执行文件）、`timeout_seconds`、`sandbox`（`none` 或 `bwrap`；`bwrap` 时只读挂载根文件系统、可写挂载工作树、关闭网络）。子进程环境去除密钥类变量（名称含 `KEY`、`TOKEN`、`SECRET`、`PASSWORD` 及 `LARK_`、`CURSOR_` 前缀）。保留 shell 元字符检查；需要管道时显式写 `bash scripts/xxx.sh` 并把 `bash` 加入 `allow`。

**验收标准。** `make test` 类命令在加入 `allow` 后可执行；超时可配置；子进程读不到密钥；`bwrap` 沙箱可用时网络不可达。

---

## 代码层面

### C1 默认图代码评审永远通过

**证据。** `workflows/default.py:424`：`status = state.get("review_status") or "pass"`，评审输出不参与判定。
**方案。** 按 D2 的结构化结论块判定；真实后端缺少结论按失败；Stub 沿用预设。随 D1 迁入编译器后由通用判定逻辑承担。
**验收。** 评审输出 `status: fail` 时退回程序员；缺少结论块时同样退回并在评审报告中注明原因。

### C2 返工时程序员看不到失败原因

**证据。** `workflows/default.py:378-397` 只传入 `task_plan`、人类需求与附件；`roles/developer/role.md` 声明的 `review_report`、`test_report`、`qa_report` 没有进入提示词。
**方案。** 返工（`dev_retry_count > 0`）时，把最近一次失败节点的报告与结论摘要作为「需要修复的问题」注入程序员提示；首轮注入 `architecture_design`。编译器的活动节点已按角色 `inputs` 注入，迁移后统一。
**验收。** 单元测试断言第二次调用程序员时提示词含评审或测试报告内容。

### C3 变更控制分支不可达

**证据。** 程序员节点只写 `code_change`；`change_control`（`default.py:401-417`）只读 `change_request`，而 `change_request` 只由升级节点写入且不含 `IMPACT:`。
**方案。** 程序员可在输出末尾给出 `change_request` 围栏块（含 `impact` 与理由），节点解析后写入 `change_request`；`change_control` 读取结构化影响范围。
**验收。** 程序员输出 `impact: scope` 的变更请求时，流程回到需求确认关卡。

### C4 Cursor 后端每次调用新建实例

**证据。** `backends/runner.py:100` 与 `backends/base.py:74` 每次调用 `try_cursor_backend()`，新建 `CursorBackend` 并调用 `Cursor.me()`；实例内的 `_agents` 缓存随之失效。
**方案。** 后端实例按「后端名 + 配置」进程级缓存；Cursor Agent 按（Run、节点、角色、工作目录、模型）复用，并把 `agent_id` 持久化到运行目录 `cursor-sessions/<摘要>.json`，进程重启后用 `resume_agent` 续接；连通性校验只在首次创建时执行。
**验收。** 同一 Run 同一节点连续两次调用只创建一个 Agent；新的后端实例能从磁盘恢复 `agent_id`。

### C5 飞书 Webhook 阻塞事件循环

**证据。** `web/feishu_routes.py:153` 为 `async def`，内部同步调用 `submit_hitl` 并跑图到下一关卡。
**方案。** 随 D4 改为写入决定并入队；路由内阻塞调用一律经 `run_in_threadpool`。
**验收。** 回调在图仍需执行时立即返回；测试中以计时断言事件循环未被阻塞。

### C6 读接口写检查点；SSE 占线程

**证据。** `hitl/service.py:1054` 的 `status_dict` 在 GET 与 SSE 轮询中调用 `note_gate_timeout` 与 `_observe`，二者可能 `update_state`；SSE 为同步生成器，每 250 ms 轮询并长期占用线程池线程。
**方案。** 读路径只读：超时与中断标记移入执行器的后台巡检（每 30 秒）；SSE 改为异步生成器，状态读取经线程池短调用，并由运行事件（节点完成、会话追加）唤醒，空闲时 2 秒心跳。
**验收。** 对等待中的运行反复 GET 不产生新的检查点；SSE 不再长期占用线程。

### C7 全表扫描与无界缓存

**证据。** `latest_run_records()`（`hitl/service.py:1224`）遍历全部检查点，被启动、起名、草稿、列表调用；`_graphs`、`_start_failures` 只增不减。
**方案。** 新增运行索引表（`run_index`：`thread_id`、`project_id`、`run_name`、`phase`、`current`、`updated_at`），在每次状态落定时更新；列表与起名查询索引；首次启动时从检查点回填。`_graphs` 改为容量受限的最近最少使用缓存，`_start_failures` 在运行结束或删除时清理并限制容量。
**验收。** 列表与起名不再调用 `saver.list(None)`；缓存容量有上限并有测试。

### C8 检查点状态膨胀

**证据。** `hitl/service.py:374` 把全部 `role.md` 正文写入 `config_snapshot_effective`；`workflow_definition` 内嵌模板全文；SQLite 检查点每步全量序列化，实测平均 52 KB/个。
**方案。** 引入内容寻址快照库 `runs/snapshots/<sha256>.json`：角色正文与流程定义写入快照库，状态只保留哈希引用；读取时按引用加载并缓存。兼容旧检查点中的内联字段。
**验收。** 新运行的单个检查点体积显著下降（测试断言状态中不含角色正文）；旧运行可正常续跑。

### C9 写锁文件与竞态

**证据。** `workspace/policy.py:90-98` 以追加方式写 PID，未截断；`_read_lock_owner_pid` 读首个 PID；`assert_write_available` 与 `exclusive_write` 之间存在竞态。
**方案。** 加锁成功后截断再写入「PID、thread_id、时间」；启动前的探测保留为快速失败提示，真正互斥由执行器领取任务时获取锁保证，失败时任务记为「等待写锁」并重试，而不是标记启动失败。
**验收。** 连续多次加锁后锁文件只含一行当前持有者信息；并发启动同一可写目录时第二轮进入等待而不是双写。

### C10 工作树与分支只建不删

**证据。** `workspace/layout.py` 只有 `git worktree add`，没有回收；`workspaces/` 已 35 MB。
**方案。** 删除运行时移除其工作树；分支在已合入基线分支或用户确认时删除，否则保留并记录。新增 `geni-studio gc` 命令清理孤立工作树（`git worktree prune`）与已删除运行的残留目录。
**验收。** 删除运行后工作树目录消失；`gc` 有测试。

### C11 会话查看依赖静态节点表

**证据。** `web/app.py:441` 用 `hitl/rail.py` 的 `NODE_ROLE` 映射节点到角色；自定义流程节点查不到；会话按角色归档，同角色多节点混在一起。
**方案。** 会话目录改为 `conversations/<节点>/<序号>.jsonl`，记录内含角色；查看接口优先按节点读取，回退到旧的按角色目录；节点到角色的映射取自运行状态中的 `workflow_nodes`。
**验收。** 自定义流程节点可以查看会话；同一角色的两个节点会话分开展示。

### C12 能力声明三处来源

**证据。** `backends/runner.py:34` 的 `ROLE_CAPABILITIES` 硬编码、`role.md` 的 `capabilities` 与别名映射并存；`codex_backend.py:105` 另有角色名特判。
**方案。** `role.md` 为唯一来源，统一词表（`read_files`、`write_files`、`run_commands`），后端声明同一词表；删除硬编码表与角色名特判。
**验收。** 只改 `role.md` 即可改变角色所需能力；相关测试覆盖。

### C13 大文件与状态码匹配

**证据。** `hitl/service.py` 1256 行混合生命周期、HITL、展示与持久化；`web/static/hitl.html` 4076 行；`web/app.py` 以 `"未知" in str(e)` 判定 404。
**方案。** 拆分为 `hitl/service.py`（生命周期与 HITL）、`hitl/presenter.py`（轨道、阅读、选项、公开字段）、`runtime/`（任务与执行器）；异常细分为 `RunNotFound`、`RunConflict`，由统一异常处理器映射状态码；`hitl.html` 的内联脚本按页面拆分为独立静态文件，加载顺序不变。
**验收。** 不再存在按错误文本判定状态码的代码；`hitl.html` 不含大段内联脚本；前端回归测试通过。

### C14 导入副作用与测试隔离

**证据。** `web/app.py:17` 导入即 `bootstrap_env()`；`workflows/default.py:850` 导入即编译并打开 SQLite；本机测试有 2 个用例因读取开发机 `.env` 失败，1 个前端用例因调用系统旧版 Node 失败。
**方案。** `.env` 加载移到 `main()` 与应用生命周期；图按需编译（`get_graph()`），`langgraph.json` 指向工厂函数；测试夹具隔离 `.env`（指向临时目录）并清除密钥环境变量；前端用例优先使用满足版本要求的 Node，找不到时跳过并说明。
**验收。** 在含真实 `.env` 的开发机上全部测试通过。

---

## 落地记录

按提交顺序追加。每条写明编号、提交、改动要点、验证证据。

- **C14**：`web/app.py` 不再在导入时加载 `.env` 和构造服务，改为生命周期内 `bootstrap_env()` 并通过 `run_service()` 惰性创建；`workflows/default.py` 以 `get_graph()` 与模块级 `__getattr__` 惰性编译默认图（`langgraph.json` 的 `default.py:graph` 引用保持可用）；CLI 的 `run`、`status`、`hitl` 命令显式加载 `.env`；`tests/conftest.py` 清除飞书、Lark、Cursor、Codex 等运行时环境变量；前端回归用例选择版本不低于 18 的 Node。验证：`tests/test_import_side_effects.py` 在子进程中断言导入后环境变量不变、默认图未编译、未打开 SQLite；全量 `pytest` 通过、`ruff check src tests` 通过。
- **C1、C2、C3、D2（结构化结论部分）**：新增 `verification/verdict.py`（结论块解析、失败即关闭判定、变更请求解析、多产物切分）；`verification/acceptance.py` 改为按结论块或验证命令输出判定验收编号；默认图的评审、测试、QA、交付按结论判定，未通过时写 `return_feedback`，程序员提示词注入「需要修复的问题」与架构设计，并可提出 `change_request`；变更控制路由后消费请求；编译器以结论块取代 `STATUS: fail` 正则，向被退回的活动注入反馈，并按产物切分输出。决策见 [ADR 0010](../decisions/0010-structured-verdicts.md)。验证：`tests/test_structured_verdict.py`（缺少结论块判失败、评审失败后第二次程序员提示含评审报告、程序员变更请求回到需求关卡、QA 只提及编号不通过、编译流程缺少结论块回退并注入反馈）；全量 `pytest` 294 通过、`ruff check` 通过。
- **C4**：新增 `backends/session.py`（会话身份摘要、落盘、文件锁），Codex 与 Cursor 共用；`try_cursor_backend` 按（API 密钥、是否校验）进程级缓存，`Cursor.me` 只在首次创建时调用，失败不缓存；Cursor Agent 以（Run、节点、角色、工作目录、模型、角色定义）为身份，`agent_id` 与「角色定义是否已发送」落盘到 `cursor-sessions/`，新实例用 `resume_agent` 续接；Codex 后端实例按（沙箱、超时）缓存。验证：`tests/test_backend_sessions.py`（两次获取同一实例且只校验一次；三个新实例中前两次复用同一 Agent 且不重发角色定义，角色定义变化时新建 Agent）。
- **C9（锁文件部分）**：`exclusive_write` 加锁后截断并写入 `pid=… thread=… since=…`，释放时清空；支持 `wait_seconds` 等待；占用提示包含持有的运行。验证：`test_write_lock_records_only_current_owner`、`test_second_writer_waits_for_release`。
- **D8**：`verification/command.py` 读取本轮冻结的 `verification` 配置，支持 `command`（字符串或列表）、`allow`、`timeout_seconds`、`sandbox`（`none`/`bwrap`）；子进程环境经 `scrubbed_env()` 去除密钥类变量；`bwrap` 模式根文件系统只读、工作树（及其 git 元数据目录）可写、隔离网络。文档见 `docs/install.md`。验证：`tests/test_verification_command.py`（未声明 `make` 时拒绝、声明后执行；超时可配置；子进程读不到 `CURSOR_API_KEY`、`LARK_APP_SECRET`、`*_TOKEN`；`bwrap` 下工作树外不可写且网络不可达）。
- **D4、C5、C6、C7、C9（执行器部分）**：新增 `runtime/store.py`（任务、控制、索引、元数据四张表）、`runtime/events.py`（每轮事件版本号）、`runtime/executor.py`（`inline`/`thread`/`external` 三种模式与 `geni-studio-worker` 入口）。`GraphRunService` 的 Web 与飞书入口改为在互斥锁内写入决定后入队（`request_hitl`、`request_resume`、`request_continue`、`enqueue_start`），同步版本保留给命令行；状态读取只读并推导阶段，超时审计与中断标记移入 `sweep()`；停止与暂停写入运行时库并由执行器同步；列表与起名改查运行索引（首次回填）；图缓存限容 64；SSE 改为异步并由事件版本号驱动；飞书 Webhook 的阻塞处理经 `run_in_threadpool`，通知只由执行器发出一次；任务遇写锁占用时延后重试。决策见 [ADR 0011](../decisions/0011-run-executor-and-runtime-store.md)。实现与方案的差异：任务表文件名为 `runtime/store.py` 而非 `runtime/jobs.py`；启动失败不单独存放，直接读取任务表。验证：`tests/test_run_executor.py`（外部模式下 HITL 与启动只入队、执行器领取后推进；Web 与飞书卡片回调立即返回运行中；另一连接写入的停止请求被执行器同步；已退出执行进程的任务在恢复时记为失败；对等待与运行中的轮次读取状态不产生新检查点；列表与起名不再扫描检查点；图缓存有上限；写锁占用时任务延后并标注「等待写锁」），`test_goal_controls.py`、`test_interrupt_resume.py`、`test_runtime_correctness.py` 改为经 `sweep()` 与执行器断言；全量 `pytest` 通过、`ruff check src tests` 通过。
- **C8**：新增 `runtime/snapshots.py`，内容按规范化 JSON 的 SHA-256 存放到检查点库同目录的 `snapshots/<sha256>.json`（内存检查点对应进程内字典），读取时校验哈希并缓存。启动时角色正文写入快照库，`config_snapshot_effective` 只保留 `_roles_ref`；编译流程的状态只保留 `workflow_definition_ref`。`roles/loader.py` 与 `workflow_definition_of()` 兼容旧运行中的内联 `_roles` 与 `workflow_definition`。同时把启动时的起名查询改为运行索引。验证：`tests/test_snapshots.py`（状态中不含角色正文且运行内可按引用读取；旧内联字段可读；相同内容只写一个文件、内容被篡改时拒绝读取；编译流程状态只含引用）；实测 `config_snapshot_effective` 从约 40 KB 降到 732 字节；`test_restart_uses_saved_workflow_not_modified_file` 证明重启后按引用续跑；全量 `pytest` 315 通过。
- **C10**：新增 `workspace/gc.py`。删除运行时移除其工作树（`git worktree remove --force`，失败时删除目录并 `prune`）与 `.geni_studio/runs/<thread_id>`；分支 `geni-studio/<thread_id>` 已是目标仓库当前分支的祖先时删除，否则保留并在返回的清理说明中注明；删除接口返回 `cleanup` 列表。新增 `geni-studio gc [--repo PATH] [--dry-run]`：以运行索引中的现存运行为准，回收各项目工作区、`GENI_STUDIO_TARGET_ROOT` 与 `workspaces/` 下不属于任何现存运行的工作树、运行目录与已合入分支。验证：`tests/test_workspace_gc.py`（删除后工作树、运行目录、空分支消失；有提交未合入的分支保留；`gc` 只回收孤立运行且 `--dry-run` 不改动；命令行输出与退出码）；全量 `pytest` 319 通过。
- **C11**：`hitl/conversation.py` 的 `begin_turn` 默认取当前图节点，把会话写到 `conversations/nodes/<节点>/<序号>.jsonl`，首条记录包含 `role` 与 `node`；不在图内调用（例如直接调用后端）时仍按角色归档。新增 `node_role(values, node)`，优先取运行状态中的 `workflow_nodes`，默认图回退到 `NODE_ROLE`。会话接口与 SSE 的会话事件按节点读取，节点目录为空时回退到旧的按角色目录。实现与方案的差异：节点目录放在 `conversations/nodes/` 下，以免节点名与旧的角色目录同名冲突。验证：`tests/test_conversation.py`（同一角色两个节点的会话分开；旧角色目录可读；自定义流程节点经接口可查看并解析出角色）；全量 `pytest` 322 通过。
- **C12**：新增 `roles/capabilities.py`，统一词表为 `read_files`、`write_files`、`run_commands`（另有后端可选的 `mcp`），旧写法 `file_read`、`file_write`、`shell` 归一后仍可识别。`required_capabilities` 只读 `role.md`，删除 `runner.py` 中的硬编码表；Cursor、Codex 后端改用统一词表声明能力；Codex 的沙箱级别由 `CodexBackend.sandbox_for()` 按角色能力决定，删除对 `developer`、`tester` 的角色名特判；编译器的并行支路检查与角色管理页共用同一词表。验证：`tests/test_role_capabilities.py`（只改 `role.md` 即改变所需能力、能力检查结果与 Codex 沙箱；旧写法可识别）；`test_cursor_backend_must_declare_run_commands_for_tester` 改为断言统一词表；全量 `pytest` 通过。
- **D7**：新增 `workspace/push_guard.py`（工作树级 `pushurl` 失效与 `pre-push` 拒绝钩子，其余钩子链接回原目录；当前分支模式按持有标记登记，本轮结束或删除时撤销），`prepare_run_layout` 在两种模式下安装。新增 `web/auth.py`：`GENI_STUDIO_WEB_TOKEN` 保护 `/api/*`，首页 `?token=` 写入 Cookie，`GENI_STUDIO_WEB_HOST` 为非回环地址且未设令牌时拒绝启动。审计行增加 `actor=`（Web 取 `GENI_STUDIO_WEB_OPERATOR`，飞书取发送者或点击者 `open_id`），HITL 接口不再读取请求体中的 `channel`；项目 `hitl.feishu.approvers` 配置后名单外飞书批复被拒绝。飞书回调未配置令牌时拒绝，内置桥接自动生成令牌，独立桥接须显式配置；本地调试可用 `GENI_STUDIO_FEISHU_WEBHOOK_INSECURE=1`（测试默认设置）。文档见 `docs/install.md`「访问控制」与「接上飞书」，决策见 [ADR 0012](../decisions/0012-security-boundaries.md)。验证：`tests/test_security.py`（运行工作树内 `git push` 与 `--no-verify` 推送均失败而主仓库可推送；当前分支模式最后一个持有者撤销后可推送；未带令牌访问 API 返回 401，请求头、Bearer、Cookie 可通过；非回环监听无令牌拒绝启动；审计含 `channel=web actor=alice` 且忽略请求体 `channel`；名单外 `open_id` 批复返回 409 且关卡不动、名单内通过并记录 `actor=ou_ok`；未配置令牌的回调返回 401 而 `url_verification` 正常；内置桥接生成令牌；文字批复记录发送者）；全量 `pytest` 335 通过。
- **D3**：`FactoryState` 增加合并式字段 `extra_artifacts`；新增 `workflows/artifacts.py`，已有字段走原字段，其余产物走 `extra_artifacts`。编译器以「名称合法」取代「必须是图状态字段」，并检查每个被读取的自定义产物都有活动产出；活动输入、输出与并行汇合统一经 `artifacts.read()`、`artifacts.put()`；`persist_values` 落盘自定义产物，产物接口接受本轮存在的自定义名称，状态接口把自定义产物展开到 `values` 顶层供前端直接展示。决策见 [ADR 0013](../decisions/0013-custom-artifacts.md)。实现与方案的差异：方案中的「有模板或显式声明」以「流程节点的 `outputs` 显式列出」实现，不额外要求模板。验证：`tests/test_extra_artifacts.py`（声明 `kernel_spec` 的流程可编译运行，下游活动提示词包含其全文；运行目录生成 `kernel_spec.md`，`/api/runs/<id>/artifacts/kernel_spec` 返回全文，未知名称 404；非法名称与无人产出的输入拒绝编译）；全量 `pytest` 338 通过、`ruff check src tests` 通过。
- **D6**：流程文件新增 `profile`（`features`、`limits`、`gates`、`skip_nodes`、`verification`），`validate_workflow` 校验类型并拒绝未知项；`build_run_context` 的合并顺序改为「项目 > 场景（兼容层）> 所选流程的 profile」，单次 Run 的覆盖仍在状态中生效；`RunContext.notices` 与配置预览接口返回迁移提示（仍引用场景、`profile_id` 不对应流程）。内置场景删除不对应的 `profile_id: *_v1`，以 `migrate_to` 指明对应流程（`npu_operator` → `npu_operator_dev`）；`factory_default`、`npu_operator_dev`、`self_improve` 补齐档案；`_example` 项目改选 `factory_default`；新建项目默认不再绑定场景。决策见 [ADR 0014](../decisions/0014-workflow-profile.md)。实现与方案的差异：场景排在流程之上，使仍引用场景的旧项目行为不变。验证：`tests/test_workflow_profile.py`（无场景的项目取流程的设计轨、重试上限与验证命令；项目覆盖流程档案；引用场景的项目可运行且预览含迁移提示；未知 `profile_id` 被提示；启动后快照冻结流程档案；非法档案拒绝保存；内置场景的 `migrate_to` 均指向已有流程）；全量 `pytest` 345 通过、`ruff check src tests` 通过。
- **D1**：编译器新增系统节点（`kind: system`，`handler` 指向 `workflows/system_nodes.py` 登记的内置实现，`routes` 与 `next` 声明去向）和 `when` 条件（`feature:design_track`、`feature:finance`、`pending:*`、`impact:*`、`failed:*`、`false:*`、`retries_exhausted`、`not:`），活动同样支持 `when`；`validate_workflow` 校验处理函数、条件与去向。`factory_default.yaml` 改写为完整流程（PM 澄清、变更控制、评审测试 QA 的回退与升级、交付判定、设计链与财务开关都在文件中），删除 `engine: default` 与 `uses_default_engine()`；`default.py` 删除手写的边、路由函数与关卡函数，`compile_graph()` 改为编译该文件；项目选择 `factory_default` 时经 `compile_for_project` 编译并冻结定义。决策见 [ADR 0015](../decisions/0015-single-engine.md)。实现与方案的差异：方案中的 `pm_clarification`、`change_control`、`acceptance`、`config_plan` 以外，默认流程的智能体节点也以系统节点形式复用原实现，尚未改写为通用活动；该流程以 `rail: builtin` 沿用内置轨道。验证：`tests/test_single_engine.py`（默认图由流程文件编译且覆盖全部处理函数；删去可测性节点后运行不再产出可测性评审；设计链开关由 `when` 决定；活动的 `when` 生效；非法处理函数、去向、条件被拒绝；选择 `factory_default` 的项目经编译器运行并冻结定义；含系统节点的流程不能作子图）；原默认图的关卡、澄清、回退升级、变更回关卡、验收对照、财务与设计链测试全部在编译后的流程上通过；全量 `pytest` 352 通过、`ruff check src tests` 通过。
- **D2（产物引用与全文传递）**：`FactoryState` 增加 `artifact_meta`；编译图的每个节点返回后由 `artifacts.record()` 登记产出节点、第几次产出、`sha256`、字数与落盘路径，并把全文写到 `.geni_studio/runs/<thread_id>/artifacts/<名称>.md`；`persist_values` 改写到同一目录并在 `manifest.json` 附带登记表，产物读取兼容旧位置。新增 `runner.backend_reads_files()`；`artifacts.reference()` 对声明 `read_files` 的后端给出路径与摘要，对 Stub 内联全文；`default.py` 与 `executable.py` 的提示词全部改用该函数，删除所有 `[:N]` 截断（含流程模板的 12000 字截断）。决策补入 [ADR 0013](../decisions/0013-custom-artifacts.md)。验证：`tests/test_artifact_meta.py`（启动后需求说明与可测性评审已登记且文件内容与哈希一致；可读文件的后端提示词只含路径、不含全文；Stub 提示词含全文；重复产出计数递增、三万字不截断；提示词构造源码中不存在 `[:N]` 截断）；`test_workspace.py`、`test_extra_artifacts.py` 改为断言 `artifacts/` 目录；全量 `pytest` 357 通过、`ruff check src tests` 通过。
- **D5**：新增 `layout.workspace_lock()`，独立工作树的写锁改为 `.geni_studio/locks/<工作树名>.lock`，当前分支模式仍锁仓库根；`exclusive_write`、`assert_write_available` 接受锁文件参数，启动与执行统一使用。新增 `workspace/branches.py`：分叉时以临时索引生成快照提交，为含写入或执行命令角色的支路建立快照工作树（安装推送防护）；支路活动在各自工作树执行；汇合时依次 `git apply --3way` 合并回本轮工作区并删除支路工作树，冲突时保留冲突标记并升级给人，继续后从汇合之后执行。删除运行与 `gc` 回收支路工作树与锁文件。升级「继续」后若下一步是关卡，改为停在关卡前（此前会直接执行关卡并报缺少决定）。决策见 [ADR 0016](../decisions/0016-parallel-worktrees-and-lock-scope.md)。验证：`tests/test_parallel_worktrees.py`（同一项目第一轮持锁时第二轮可以启动，第一轮的锁仍互斥，删除运行后锁文件消失；程序员与测试两条写入支路并发执行于不同工作树，汇合后两路新文件都在本轮工作区，支路工作树已删除；两路改同一文件时升级给人、说明列出文件、工作区含冲突标记，人工处理后继续停在下一关卡）。同时修复测试隔离：`tests/conftest.py` 预先导入全部模块，避免模块首次导入发生在打桩期间而把桩函数留在模块中（此前 `test_subgraph_parallel.py` 之后单独运行 `test_workspace_gc.py` 会失败）。全量 `pytest` 360 通过、`ruff check src tests` 通过。
- **C13**：新增异常类型 `RunNotFound`、`RunConflict`、`NotAwaiting`（`RunBusy` 归入 `RunConflict`）与 `ConfigNotFound`，在运行、草稿、场景、项目、流程、角色的「不存在」与「名称不一致」处抛出；新增 `web/errors.py`（`status_for`、`http_error`、全局异常处理器），`app.py`、`config_routes.py`、`workflow_routes.py`、`role_routes.py` 删除全部按错误文本判定状态码的代码，`feishu_routes.py` 以 `NotAwaiting` 类型识别过期卡片；轨道、阅读、选项、公开字段与超时提示移到 `hitl/presenter.py`（`service.py` 由 1626 行降到 1458 行，生命周期与任务部分此前已在 D4 移入 `runtime/`）；`hitl.html` 主脚本原样移到 `static/hitl.js` 并在原位置同步引入（页面由 4076 行降到 901 行，仅保留约 20 行的主题初始化内联脚本）。决策见 [ADR 0017](../decisions/0017-typed-errors-and-presenter.md)。实现与方案的差异：脚本未进一步按页面拆分，先整体外置以保证加载顺序与全局作用域不变。验证：`tests/test_web_boundaries.py`（状态码随异常类型；`web/` 下无文本匹配；未知运行与草稿返回 404、草稿名称不一致返回 409；展示层输出结构；页面无大段内联脚本且 `hitl.js` 可访问并通过 `node --check`）；读取页面源码的 5 个用例改为同时读取 `hitl.js`；`tests/config_runtime_regression.cjs` 通过；全量 `pytest` 通过、`ruff check src tests` 通过。
- **D1 后续：默认流程智能体步骤改为通用活动**：`factory_default.yaml` 中调用 Agent 的 16 个步骤改为 `kind: activity`，提示词由编译器按通用活动拼装（含返工反馈、输入产物、这一步选用的 Skill 与 MCP）；每步特有的写作要求写入新增字段 `instruction`；原系统节点中的判定与状态写入（返工计数、变更请求、评审/测试/QA 结论、验收对照、交付前检查、复盘、预算阶段）改为活动的内置后处理 `effect`（`system_nodes.EFFECTS`，实现在 `default.py`）；活动可写 `routes`/`next`；系统节点只保留不调用 Agent 的六个步骤。只写名称、且在角色契约中的输出不要求模板；多产物按产物名二级标题切分，切分只以产物名标题为界。内置轨道把不调用 Agent 的格子标为 `system`，运行页不为其显示模型与 Skill/MCP。决策见 [ADR 0019](../decisions/0019-default-flow-agent-steps-as-activities.md)。验证：`tests/test_single_engine.py`（默认流程起草与可测性两步的提示词各自只含本步选用的 Skill 与 MCP；流程中的 `effect` 与实现登记一致；未知后处理、回退与 `routes` 并写被拒绝；角色契约内的纯名称输出可免模板，契约外或对象形式仍须模板），`tests/test_rail.py`（内置轨道格子种类）；直接调用节点的用例改用 `run_builtin_node`；全量 `pytest` 389 通过、`ruff check src tests` 通过。
- **C4 后续：角色会话按 Run 复用，Cursor 加载项目与用户配置**：Cursor 与 Codex 后端的会话标识去掉节点 ID，同一角色在一个 Run 中共用一个会话，跨节点延续上下文，role.md 只随首条消息发送一次；对话记录仍按节点归档。Cursor 后端按会话标识串行发送，避免只读并行支路同时向同一 Agent 发消息。Cursor 本地智能体设置 `setting_sources=("project", "user")`：SDK 默认只加载内联配置，实测默认情况下看不到任何 Skill、MCP 服务器与工作区规则，加载两层配置后均可见。决策见 [ADR 0020](../decisions/0020-role-session-per-run-and-cursor-settings.md)。验证：`tests/test_backend_sessions.py`（同一角色在两个节点只创建一个 Agent，第二个节点的消息不含角色定义，对话按节点分目录，创建参数含两层配置）；`tests/test_cursor_reasoning.py` 改为断言跨节点只建一个会话；以真实 Cursor SDK 在临时目录实测 Skill、MCP 与规则的加载；全量 `pytest` 390 通过、`ruff check src tests` 通过。
- **MCP 改为全局配置**：与 Cursor IDE 一致，后端加载的 MCP 服务器对所有角色可见。运行页去掉节点的 MCP 选择，`node_tools` 与 `PUT /api/runs/<id>/nodes/<node>/tools` 只保存 Skill，旧状态中的 `mcp` 字段读取时忽略；提示词改为「这一步优先使用下面的 Skill」。配置页 Agent 下按所选后端只读列出 MCP 服务器：`GET /api/config/tools` 增加 `backend`、`project_id` 参数，Cursor 读取所开项目工作区与用户目录的 `.cursor/mcp.json`，Codex 读取 `$CODEX_HOME/config.toml` 的 `mcp_servers`（跳过 `enabled = false`）。决策补入 [ADR 0020](../decisions/0020-role-session-per-run-and-cursor-settings.md)，界面规范同步 `docs/design/ui-ux.md`。验证：`tests/test_backend_tools.py`（提示词只含 Skill；目录按所请求的后端与项目工作区读取，不含命令与密钥）、`tests/test_implemented_round.py`（配置页 Agent 区有只读 MCP 列表，运行页脚本不再有 MCP 选择）；全量 `pytest` 392 通过、`ruff check src tests` 通过；预览服务中检查配置页与运行页布局。
