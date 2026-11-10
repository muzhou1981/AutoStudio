# 0009 · 运行正确性与 Codex 适配修复

- 状态：已实现；验证结果与证据范围见第 6 节。
- 代码基线：`4389ea4`（2026-11-10）。本轮从该基线的干净工作区重新审阅，没有恢复 stash 或套用旧补丁。
- 范围：后端调用、流程调度、状态恢复、人工关卡、验证证据与配置交互。
- 文档目的：说明本次修改解决了什么错误、如何解决、验证到什么程度；不包含 Codex 安装、登录或调用教程。

本文中的“原实现”指上述基线，“当前实现”指本轮修复后的工作区。下面将故障机制、实现变化和验证证据分开描述：已有测试通过不意味着同类问题在任意运行环境下都得到保证，未覆盖范围集中列在第 7 节。

## 1. Codex 调用链的正确性

实现主要位于 [codex_backend.py](../../src/geni_studio/backends/codex_backend.py)，调用入口见 [runner.py](../../src/geni_studio/backends/runner.py)，会话记录见 [conversation.py](../../src/geni_studio/hitl/conversation.py)。

### 1.1 线程缓存存在，但真实角色调用没有复用会话

**触发条件与错误行为。** 同一 Run 内，同一角色被重复调用，例如测试角色先生成测试用例，再生成测试报告。原 `CodexBackend` 把 SDK Thread 存在实例的 `_threads` 中，但 `invoke_role → backend_for_role` 每次返回一个新的后端实例。第二次调用拿到的是空缓存，因此会重新创建线程。直接复用一个后端对象的单元测试可以通过，实际工厂调用仍会丢失上下文；服务重启也会丢掉实例缓存。

这会造成两个后果：角色无法继续上一轮对话，调用日志看起来属于同一角色，但实际是多个独立会话；反复重发上下文也会增加成本。

**修复机制。** 后端实例保存线程标识，Run 运行目录另外保存 `codex-sessions/<摘要>.json`。一次调用按以下顺序执行：

1. 确定当前 Run、节点和工作目录，计算会话身份摘要。
2. 获取对应会话文件的排他锁，再打开 SDK 客户端。
3. 优先读取已落盘的 `thread_id`；存在时调用 `thread_resume`，不存在时调用 `thread_start`。
4. 保存返回的线程标识，然后发起本次 turn。
5. turn 处理完成或发生异常时关闭客户端，持久化线程标识继续留给下一次调用。

因此，连续两次 `invoke_role` 即使创建不同的 `CodexBackend`，仍能通过磁盘上的 thread ID 续接。恢复已有线程失败时直接抛错，不偷偷新建会话掩盖历史丢失。

会话文件通过同目录临时文件加 `replace` 更新，避免读到写了一半的 JSON；会话锁使用 `fcntl.flock`。这里没有增加磁盘 `fsync`、事务日志或故障回放协议，不能把它解释成断电恢复或副作用 exactly-once 保证。

**验证。** `test_actual_role_invocation_resumes_across_backend_instances` 覆盖实际角色调用入口；真实 SDK 用例 `test_live_codex_resume` 使用两个后端实例完成记忆与回忆，并检查 SDK thread ID 相同。后者证明跨实例、跨 SDK 客户端恢复，不等同于完整服务进程被杀死后的恢复测试。

### 1.2 会话身份缺少节点、沙箱和角色提示版本

**原问题。** 原缓存键包含 Run、角色、工作目录和模型，但不包含工作流节点、沙箱或系统提示。缓存一旦得到复用，同一个角色承担不同活动时就可能继承不属于该活动的对话；角色说明或权限配置改变后，也无法从键上区分旧会话。

**修改。** 当前会话身份为以下内容的 SHA-256 摘要：

```text
Run ID
+ LangGraph 节点 ID
+ 角色名
+ 解析后的绝对工作目录
+ 归一化后的模型名
+ 沙箱模式
+ 角色系统提示正文
```

节点 ID 从当前 LangGraph 配置的 `metadata.langgraph_node` 读取。相同节点、角色和配置可继续原线程；不同节点或配置会得到不同的映射文件。角色提示通过 `developer_instructions` 传入，turn 的正文保持为本次用户任务；恢复线程时也传入同一组线程选项。

没有绑定 Run 的直接调用不落盘共享映射，只在同一后端对象内缓存线程 ID；没有图执行上下文时节点 ID 为空。不能据此声称所有脱离工厂的并发调用都已有独立会话管理。

**验证。** `test_role_sandbox_and_identity` 检查角色提示改变后创建不同线程；跨实例和真实 SDK 续接用例检查身份保持不变时可以恢复。节点隔离字段来自代码核对，本轮没有额外执行跨节点的真实模型串扰测试。

### 1.3 没有工作区时可能改到工厂仓库，角色权限也未区分

**原问题。** `_cwd()` 原先在 `current_worktree()` 为空时回退到工厂根目录，同时所有 Codex 角色固定使用可写沙箱。关闭工作区模式仍可能产生真实文件操作；只读分析角色也获得了写入能力。

**修改。** Codex 调用前要求当前工作区存在且为目录，再将其解析为绝对路径；缺失时直接报错。这个检查验证的是工作目录是否有效，独立 Git 工作树的创建仍由既有 workspace 层负责。

沙箱选择按以下规则执行：

| 情况 | 当前行为 |
|---|---|
| 角色是 developer/tester，或声明 `file_write` | 默认使用 `workspace-write` |
| 其他角色，没有显式沙箱覆盖 | 默认使用 `read-only` |
| 需要写入的角色显式指定只读 | 在启动线程前拒绝 |
| 显式沙箱不是上述两种 | 创建后端时拒绝 |

这不是“所有管理角色都只读”：例如现有 architect 的角色定义声明了写文件能力，仍会获得可写工作区。没有写入需求的角色也可以通过显式配置选择 `workspace-write`，本次没有取消这一配置能力。

线程选项明确使用 `ApprovalMode.deny_all`，避免在没有接好 SDK 审批交互的情况下让需要额外批准的操作自动放行。它与工厂的需求确认、架构评审等 HITL 关卡属于不同层级，不能相互替代。

**验证。** `test_real_workspace_required`、`test_role_sandbox_and_identity`；真实开发闭环在临时 Git 工作树中完成文件写入和测试。该工作区检查是 Codex 后端的修改，没有将 Cursor 的工作目录回退逻辑一并重写。

### 1.4 停止按钮与 SDK 中断接口不匹配

**原问题。** 工厂的 `cancel_active_runs()` 调用活动对象的 `cancel()`；原 Codex 后端直接注册 SDK TurnHandle，而其接口是 `interrupt()`。因此停止请求虽然被记录，正在执行的 SDK 调用未必会被中断，可能一直等到 `handle.run()` 自然返回。

**修改。** 注册对象改为 `_ActiveTurn`，由它实现工厂约定的 `cancel()`：

1. 在辅助线程调用 Handle 的 `interrupt()`。
2. 最多等待 0.5 秒，避免中断 RPC 本身阻塞停止路径。
3. 关闭客户端，使仍等待事件的消费逻辑能够退出。
4. 后端异常路径检查停止标记；停止引起的传输关闭等异常统一转为 `RunStopped`。
5. 在 `finally` 中移除活动对象，避免之后的停止请求命中已结束调用。

发起 turn 后、开始消费前也会检查停止标记，以处理注册活动对象附近到达的请求。

**验证。** 契约测试检查适配器确实调用 SDK interrupt。真实用例 `test_live_codex_stop_interrupts_active_command` 等待 `commandExecution` 开始后发送停止，调用在测试限定时间内以 `RunStopped` 结束。这证明后端与运行控制接口的链路，不是浏览器按钮自动化测试，也不证明任意外部子进程或远程任务均已被撤销。

### 1.5 登录异常泄漏客户端，调用缺少有效时限

**原问题。** 原 `_open_codex()` 构造客户端后执行 API Key 登录，登录抛异常时调用方拿不到客户端，无法清理；长期持有的客户端也没有统一的关闭边界。没有时限时，认证、恢复或事件读取可能长期占住执行线程。

**修改。** `_open_codex` 改为上下文管理器：客户端成功构造后创建守护计时器，超时设置标记并关闭客户端；异常路径根据标记转换为 `TimeoutError`；最终始终取消计时器并关闭客户端。模型目录和账号探测也使用这一管理路径。

后端默认时限为 1800 秒，探测路径默认 30 秒；有限正数校验拒绝零、负数、NaN 和无穷大。计时范围包含客户端构造完成后的登录、线程操作与 turn 消费。

**边界。** 会话文件锁等待、`Codex()` 内部进程启动和初始化均在计时器启动前，本次没有为它们提供端到端超时。超时关闭客户端也不代表回滚已完成的文件修改。

**验证。** `test_invalid_timeout`、`test_login_failure_closes_client`、`test_timeout_closes_client_and_unblocks` 使用替身客户端检查清理与异常转换，没有真实网络超时故障注入。

### 1.6 最终结果判定不够严格，会话缺少中间证据

**原问题。** 原实现依赖 `handle.run()` 的聚合结果，再用少数失败状态做排除；适配器自身没有要求状态必须为 `completed`。日志只有提示和最终正文，无法看到运行中的工具步骤或区分中间说明与最终交付。

**修改。** `_consume_turn` 消费公开通知流，通过 SDK 类型的 `model_dump(mode="json", by_alias=True)` 获取协议字段，分别处理：

| 通知 | 处理规则 |
|---|---|
| `item/completed` | 仅从匹配当前 turn ID 的 `agentMessage` 提取文本；优先 `phase=final_answer`，保留无 phase 消息作兼容回退；commentary 不作为结果 |
| `thread/tokenUsage/updated` | 仅采纳当前 turn ID 的用量 |
| `turn/completed` | 记录当前 Handle ID 对应的终态 |

只有收到匹配终态、`status == completed`、`error is None`，且最终文本非空时才返回正文。失败、中断、仍在执行、缺失终态或只有 commentary 都不能被当作成功。流无论正常结束还是异常退出都会关闭。

Run 调用会记录 `turn → step… → result`；失败时追加异常类型，而不主动把异常全文写回日志。记录仍使用已有的 `_plain` 归一化与长度限制，因此是面向观察的日志，不是无截断的协议备份，也不能据此宣称所有提示、工具输出都经过敏感信息脱敏。

**验证。** `test_only_successful_terminal_turn_returns_text` 覆盖 failed/interrupted/inProgress，`test_commentary_is_not_final_response` 检查中间说明不会成为结果；真实 SDK 用例检查存在事件记录和最终结果。替身事件采用真实 SDK 通知类型，没有用自定义假字段代替协议结构。

### 1.7 token 和模型字段与实际 SDK 不一致

**token 问题。** 原 `_cost_line` 在 usage 顶层查找 input/output token，而真实返回是 `ThreadTokenUsage.last` 与 `total`，因此正常调用也可能被记为 unknown。若直接改读 `total`，持续会话又会把之前的用量重复计入。

当前从 `last` 读取本次用量，兼容字典中的驼峰字段和 SDK 对象中的蛇形字段；输入或输出用量缺失时返回 unknown，不填造零值。最小真实 SDK 调用确认了该数据结构，`test_explicit_model_and_real_sdk_usage` 检查提取结果。

**模型问题。** 原 `_model_rows` 优先读取目录条目的 `id`。目录行标识与调用所需的模型名可能不同，导致页面可以选中一个条目，实际请求却使用错误名称。现在从 `ModelListResponse.data` 读取条目的 `model` 作为请求 ID，`display_name` 只用于显示；测试专门构造 `id != model` 的条目验证。

### 1.8 会话日志编号竞争与测试替身污染

原日志编号使用“已有文件数 + 1”。两个并发调用可以得到同一编号；若中间文件被删，文件数量也可能指向已存在的文件，最后把两次对话追加到同一个 JSONL。

`begin_turn` 现在从候选编号开始，以 `touch(exist_ok=False)` 排他创建；遇到冲突递增重试。该修改保证调用不会因为这一编号算法共享日志文件，不保证在崩溃时空占位文件一定有完整内容。

原 SDK 测试直接改写 `sys.modules["openai_codex"]`，而且假对象的 usage、models 等结构与真实 SDK 不一致。这既可能污染后续测试，也使实际接口错误被测试替身掩盖。当前测试导入真实 SDK 类型，仅替换客户端/进程边界；真实调用测试另行保留。依赖固定为 `openai-codex==0.167.0`，明确本轮验证针对的协议版本。

## 2. 后端选择与配置交互

相关实现：[base.py](../../src/geni_studio/backends/base.py)、[runner.py](../../src/geni_studio/backends/runner.py)、[cursor_backend.py](../../src/geni_studio/backends/cursor_backend.py)、[connectivity.py](../../src/geni_studio/config/connectivity.py)、[registry.py](../../src/geni_studio/config/registry.py)、[config.js](../../src/geni_studio/web/static/config.js)。

### 2.1 不可用的真实后端被悄悄替换成 Stub

原默认后端选择包含 `try_codex_backend() or StubBackend()`，Cursor 也有同类路径。SDK 缺失、认证/桥接配置不满足时，流程仍可能生成占位产物，用户却以为所选真实后端完成了工作。未知角色后端名称还可能落回默认后端，隐藏拼写错误。

现在 Stub 必须显式选择；选中 Codex 但 SDK 不可用时直接报错，选中 Cursor 但后端不可用时提示检查 SDK、凭证和桥接。未设置后端时仍按项目需求选择 Cursor，不再因没配凭证就变成模拟执行。未知后端直接拒绝；模型目录接口遇到未知名称返回错误说明，不再伪装成 Stub 目录。

探测逻辑与此保持一致：未知后端返回失败；缺少 Cursor Key 是失败，不再因为飞书或工作区检查成功而给人 Agent 已就绪的印象。

**兼容性影响。** 过去依赖“环境没配好也能跑通”的调用需要明确选择模拟后端。对应回归从检查隐式 Stub 调整为检查明确报错。

### 2.2 角色级选择被全局开关阻止，能力检查覆盖不全

原角色配置即使明确选择 Cursor，仍调用受全局 `GENI_STUDIO_BACKEND` 控制的 `try_cursor_backend()`；当全局是 codex/stub 时，角色覆盖无法生效。现在该路径使用 `force=True`，只跳过全局启用判断，SDK、凭证与桥接检查仍保留。

原能力要求只硬编码 developer/tester，其他角色 Markdown 中声明的操作能力没有完整参与校验。现在 `required_capabilities` 读取角色定义，并与内置最低要求合并：

| 角色定义字段 | 后端接口能力 |
|---|---|
| `read_files` | `file_read` |
| `write_files` | `file_write` |
| `run_commands` | `shell` |

非 Stub 后端缺少任一要求时抛出 `CapabilityError`。这些声明是能力协商依据；真正的文件访问限制仍由后端沙箱执行，不能把“声明支持 shell”理解为每条命令都会被允许。

本次针对 Codex 实现了持久线程恢复；Cursor 原有实例缓存的复用问题没有因此自动解决，见第 7 节。

### 2.3 共享默认模型跨后端传播

**故障示例。** 全局 Cursor 配了共享默认模型，项目中的 developer 单独使用 Codex。原 `factory_default_model()` 优先返回共享值，可能把 Cursor 模型名传给 Codex。配置页切换供应商时也会保留上一供应商的选项。

**后端修改。** `factory_default_model(backend)` 先读取指定后端的默认模型；旧 `GENI_STUDIO_DEFAULT_MODEL` 仅在目标后端等于当前全局后端时作为兼容回退。角色模型仍遵循“本轮角色选择 → 项目/场景中的角色模型 → 对应后端默认值 → SDK 默认”的决议顺序；进入 Run 后，默认项从快照读取。

**页面修改。** 默认模型分开保存到各后端专属字段。切换后端时，若旧共享模型尚未迁移，则先把它保留在原后端字段，再保存新后端选择并清空共享字段。选择 Stub 时不写空 Cursor/Codex 专属模型。`defaultModelFromSettings` 也不再拿另一个后端的默认值填充当前选择。

**验证。** `test_models_are_scoped_to_selected_backend` 验证服务端隔离；Node.js 回归检查共享模型迁移、Codex 新模型写入及切换 Stub 后保留原模型。

### 2.4 配置页异步响应覆盖新选择，保存失败后按钮卡住

存在两个不同问题：

- 用户先选择 Cursor、随后选择 Codex，较慢的 Cursor 模型请求最后返回，可能覆盖 Codex 页面内容。
- 保存多个配置项的 `fetch` 循环原先在 `try/finally` 外；网络断开或 JSON 解析失败时跳过按钮恢复逻辑，页面一直显示保存中。

模型列表请求现在带递增版本号，返回时核对请求版本和当前后端；`syncBackendFields` 写入密钥元数据前也检查后端是否仍为发起请求时的选项。旧后端的迟到响应不再覆盖新后端。

配置写入请求循环和后续探测都纳入 `try/finally`，异常后恢复按钮状态。异常提示说明部分配置可能已保存，而不是暗示整个操作原子成功。这里没有新增批量配置事务，逐项写入中途失败仍可能留下部分新值。

`settings_status` 同时按 `{文件配置, 进程环境覆盖}` 计算展示值。服务进程实际读取环境变量时，页面不再只展示 `.env` 中另一套后端或模型配置。

**验证。** `config_runtime_regression.cjs` 执行真实页面函数，替换 DOM 与 fetch，验证断网后按钮恢复、模型迁移及保存内容；这不是完整浏览器自动化，也没有覆盖所有异步响应排列。请求版本检查本轮通过代码核对与 JavaScript 语法检查。

### 2.5 SDK 启动、账号状态和实际推理被混为一谈

原 `probe_codex` 只要成功构造 SDK 客户端就返回“可用”。客户端启动、账号已登录、某个模型能完成生成是三件事，前一项不能证明后一项。

现在探测读取 `client.account()`；需要 OpenAI 认证但没有账号时失败。成功文案明确表示启动与认证状态就绪，且尚未验证推理。SDK 目录查询成功也不再被描述成所有模型均可调用。

原 API Key 校验先 `login_api_key` 再 `models()`，既可能只写本地认证、读本地目录，也可能在校验阶段改变本机登录缓存。现在校验通过带 Bearer 认证的 OpenAI 模型列表 HTTP 请求完成，不调用 SDK 登录。失败只返回通用错误，不回显提交的 Key。

这仍是“模型目录接口认证检查”：未验证额度或具体模型的生成权限；没有目录读取权限的受限 Key 也可能无法通过当前检查。正常 Codex 执行路径仍可以使用 Key 登录并影响本机 SDK 认证缓存，本次只去除了**密钥校验阶段**的这一副作用。

**验证。** `test_probe_requires_account` 检查没有账号时失败；HTTP 401 替身测试检查失败返回及密钥不回显。真实生成权限由第 6 节的实际 SDK 调用验证，使用的是本机 ChatGPT 登录，不是 API Key 推理。

### 2.6 工作区可写探测破坏同名文件

原探测固定写入 `.geni_studio_write_probe`，随后删除。若用户已经有这个文件，检查本身会覆盖并删除用户数据。

现在在目标目录使用 `tempfile.TemporaryFile` 创建临时文件，写入后由上下文关闭清理。`test_workspace_probe_does_not_overwrite_existing_file` 预先放入同名文件，确认探测成功后原内容仍在。这项修复只改变探测文件的生命周期，没有改变工作区目录验证规则。

## 3. 调度、暂停与人工关卡

主要实现：[executable.py](../../src/geni_studio/workflows/executable.py)、[default.py](../../src/geni_studio/workflows/default.py)、[service.py](../../src/geni_studio/hitl/service.py)、[transaction.py](../../src/geni_studio/hitl/transaction.py)、[gate.py](../../src/geni_studio/hitl/gate.py)、[rail.py](../../src/geni_studio/hitl/rail.py)。

### 3.1 不等长支路可能提前汇合，后继节点可能执行多次

**触发例子。** A 支路只有 A1，B 支路包含 B1 → B2 → B3。原图分别把 A1、B3 连到 join；这两个普通边不能表达“必须等两条支路都结束”。A1 完成时 join 可能先执行，使用不完整产物启动下游；B3 完成后又可能再次触发 join。

**修改。** 每条支路增加独立完成节点，并使用一个多起点边构造等待屏障：

```text
fork → A1             → A_done ┐
                               ├─ 等待全部完成 → join → after
fork → B1 → B2 → B3   → B_done ┘

实际汇合约束：add_edge([A_done, B_done], join)
```

关键不是多画了两个节点，而是用一次 `add_edge(全部完成节点, join)` 表达共同前置条件，而非分别连接 join。join 再按支路顺序合并产物。

**验证。** `test_unequal_parallel_branches_wait_and_read_local_outputs` 执行真实 LangGraph，角色调用用确定性替身；检查下游能看到 B3 的结果且只执行一次。原先仅有等长支路的测试不足以揭露这个问题。

### 3.2 支路写入局部产物，后续活动却读取全局旧值

原 `_activity_update` 把支路产物写入 `branch_artifacts`，键形如 `并行节点:支路:产物名`；但 `_activity` 组装输入时只读 `state[产物名]`。因此 B1 已经输出新结果，B2 仍可能读到并行开始前的旧值或空串。

现在支路内活动先查自己的局部键，存在时使用本支路产物；该键不存在才回退到全局输入。不同支路不会通过同名全局产物相互覆盖。

另外，`branch_artifacts` 使用合并 reducer，进入下一轮不会自动清空。`_fork` 将当前并行区域已有的局部键置空，避免外层回退后读取上一轮结果。这里是重置值，不是删除整个 Run 的支路映射。

编译过程还将节点列表改为深拷贝，防止 `_link_one` 写入 `graph_return` 等派生字段时修改调用者的流程定义或共享嵌套对象。

**验证。** 不等长支路用例预置 `stale-global`，检查 B2 实际获得 B1 的新结果、B3 获得 B2 的新结果，并确认编译前后的输入定义相等。外层多轮重入的清理机制已实现，本轮没有单独将它列为已完成的真实模型测试。

### 3.3 复杂并行无法正确表达，却被当作可执行流程

当前状态只有单个人工待办和决定槽位，工作区也没有按支路隔离。直接支持并行关卡、分支回退或多个写入角色，会引入待办串用、跨支路跳转和文件冲突。

本次增加的是明确拒绝，不是完整实现这些能力：

| 检查位置 | 拒绝条件 | 原因 |
|---|---|---|
| `compile_workflow → _validate_parallel` | 支路步骤不是普通 activity，或存在 `returns_to` | 当前屏障与单待办模型不能正确覆盖关卡、回退、嵌套并行 |
| 并行入口 `_fork` | 已有工作区，且任一步骤声明写文件或执行命令能力 | 同一工作区尚无支路写入隔离；命令也可能产生写入 |

内置 `llm_fullnet` 仍可查看和编辑，但其中包含上述复杂结构，编译执行会被拒绝；路线图相应从“已完成”改为“部分完成”。对其后续实现，应设计独立待办、支路状态和工作区合并机制，而不是删除校验后继续运行。

**验证。** 参数化用例覆盖关卡、回退、嵌套并行三类拒绝；原内置流程测试改为断言明确报错。共享工作区写入限制来自入口代码检查，本轮未执行真实并行写冲突实验。

### 3.4 暂停会丢弃已完成结果，续跑重复调用

原实现同时在后端返回、`invoke_role` 返回及节点返回附近检查暂停并抛异常。若模型已经修改文件并返回正文，异常发生在节点更新提交之前，检查点仍认为该节点没有完成；恢复时就可能再次调用模型或执行命令。

| 时点 | 原行为 | 当前行为 |
|---|---|---|
| 节点进入前已经收到暂停 | 阻止执行 | 仍阻止执行 |
| 当前模型调用期间收到暂停 | 调用结束后可能抛异常，结果丢失 | 当前节点继续完成并返回更新 |
| 一个节点包含多次角色调用 | 中间调用边界可能抛暂停异常 | 允许当前节点内的调用完成，节点入口控制后续调度 |
| 下一节点准备进入 | 可能重试上一节点 | 在下一节点前暂停，上一节点结果已保存 |

这定义了**节点边界暂停**。若当前节点直接进入人工关卡或结束，没有下一普通节点可拦截，最终状态可以是等待人工或已完成，而不强制改为 paused。停止仍可在调用中中断，不能把暂停的结果保留承诺套用到强制停止。

**验证。** `test_pause_after_completed_call_keeps_node_output` 在第一个活动中发出暂停，验证产物保留、`next_nodes` 指向第二个活动，恢复后调用顺序恰好为 first、second。既有 HITL 测试也改为期待保留已结束的项目经理产物。

### 3.5 暂停掩盖真实异常，内部节点在页面上显示“无”

原 `_invoke` 在捕获任意异常后，只要发现暂停标记就不再抛出。这可能把解析错误或后端错误显示成一次正常暂停。

现在区分控制流异常 `RunPaused/RunStopped` 与普通异常；普通异常在没有停止请求覆盖时标记 interrupted 并继续抛出，不能仅因 pause 标记就消失。`test_pause_does_not_hide_real_exception` 同时触发暂停与 `ValueError`，检查异常和 interrupted 状态。

节点边界暂停也暴露了显示问题：检查点可能停在 `pm_clarification_check` 等内部节点，轨道中没有对应格子，原 paused/interrupted 分支直接显示“无”。当前把 `paused_at` 与 `next_nodes` 中的候选节点经过 `_INTERNAL_TO_RAIL` 映射，保留实际检查点位置，同时在界面显示对应业务节点。Web/飞书使用相同轨道结果。

### 3.6 同一 Run 并发修改检查点，查询也可能抢写状态

原服务对“读当前状态 → 校验 → 更新 → 执行”没有覆盖全段的互斥。两个请求可以同时看到相同待办，各自提交决定；一边执行另一边改模型或删除 Run，也会破坏状态一致性。

新增 `run_mutation` 按 `thread_id` 获取可重入非阻塞锁，覆盖 `_invoke`、HITL 提交、resume、continue、删除、节点工具/角色模型修改和打开待办。需要可重入，是因为提交方法内部还会调用 `_invoke`；竞争请求抛出 `RunBusy`，不排队到后续状态才执行。弱引用锁表避免空闲 Run 长期保留锁对象。

状态查询存在另一个写入点：`_observe` 可标记 interrupted，`note_gate_timeout` 可写等待时间和超时记录。如果查询恰好发生在某个变更已经开始、`is_inflight` 尚未登记的间隙，原逻辑会误判为没有执行体的运行。

现在这两个方法使用 `observation_mutation`。拿到同一 Run 的锁时才允许更新；锁被其他请求持有时，仅调用 `status()` 读取检查点，不额外标记中断或超时。

**验证范围。** `test_reject_concurrent_hitl_for_same_run` 实际测试的是通用装饰器的线程互斥，不是两路真实 HTTP 审批；`test_observation_does_not_mark_in_progress_mutation_interrupted` 在另一线程持锁时读取状态，确认未写入误中断标记。

这不是全服务的数据库事务：启动准备、停止/暂停信号及所有外部副作用没有统一纳入这一锁。锁也不是跨进程锁，不能据此启动多个服务实例共同推进同一 Run。

### 3.7 缺少决定默认批准，澄清答复可能越过关卡

原 `apply_gate_node` 在 `gate_decision` 缺失或非法时取 approved，且消费后不清除该字段。正常 Web 路径虽然会校验提交，其他恢复路径或遗留状态仍可能触发隐式批准，甚至沿用上一关的决定。

当前要求关卡节点收到明确的 approved/rejected，否则报错；成功消费后把 `gate_decision` 清为 `None`。`last_gate_decision` 仍用于路由与结果展示，批准依据继续写入 baseline log。

PM 澄清原路径更新答复后直接 `_invoke(None)`。若当前 next 已经是一个被 interrupt 的关卡，直接 invoke 会恢复并执行关卡，而“回答问题”并不等于“批准方案”。现在更新澄清内容后重读快照，若下一节点是默认或自定义关卡，就返回等待人工；仅在没有关卡时继续推进。

**验证。** `test_gate_never_implicitly_approves` 检查空/非法决定被拒绝和消费后清除；已有 PM/HITL 回归与真实开发闭环继续通过。本次没有新增持久待办 ID 或幂等回执，旧审批请求的顺序重放仍属于未解决边界。

## 4. Run 定义与配置恢复

实现见 [service.py](../../src/geni_studio/hitl/service.py)、[runtime.py](../../src/geni_studio/backends/runtime.py)、[context.py](../../src/geni_studio/config/context.py)、[loader.py](../../src/geni_studio/roles/loader.py) 及流程编译器。

### 4.1 旧 Run 可能套用最新 YAML，缓存又按 workflow ID 共享

原 `_bound` 重建所选流程时读取当前 workflow 文件，`_compiled` 还按 workflow ID 缓存。假设 Run A 正在等待架构批准，这时用户编辑同名流程并创建 Run B：服务重启或重新绑定后，A 可能使用 B 对应的新节点和边，与 A 的已有检查点不一致。

现在 `compile_for_project` 将展开后的定义写入 `workflow_definition`，`_bound` 从该 Run 的检查点读取定义并编译，只按 Run ID 缓存其图。源码中的派生路由字段不会反向污染保存的定义。

活动显式引用的本地模板正文也在准备阶段存入 `output_specs.content`，上限保留既有的 12000 字符。`_template_section` 优先使用这一内容，文件之后被修改不影响这轮相应活动。远程模板链接、默认 Python 图的其他模板读取不因此被冻结。

**验证。** `test_restart_uses_saved_workflow_not_modified_file` 先启动 Run，修改流程文件，再使用同一 MemorySaver 创建新的 GraphRunService；批准后仍得到 original 而非 changed。这验证服务对象重建时使用快照，没有执行 SQLite 故障恢复或整个进程重启测试。

### 4.2 保存了配置文本，但执行仍读最新配置

原场景/项目 YAML 快照主要用于记录；角色后端、模型、能力和测试命令等执行路径仍可能读取当前文件或进程环境。等待人工期间更改配置，旧 Run 后半程就可能换后端、角色提示或验证标准。

当前新增 `config_snapshot_effective`，保存合并后的生效配置以及本轮额外字段：

| 内容 | 读取方式 |
|---|---|
| 合并后的项目/场景配置 | `build_run_context_from_state` 优先据此构造 RunContext |
| `_backend` | 未显式覆盖角色后端时使用当轮默认值 |
| `_models` | 保存 Cursor/Codex/Stub 对应默认模型的决议结果 |
| `_test_command` | 保存当时环境或项目配置中的验证命令 |
| `_roles` | 保存角色 Markdown，执行时用于提示和能力解析 |

`_invoke_body` 在图执行期间通过 `use_config` 绑定 ContextVar，执行结束后恢复原上下文，避免不同 Run 在同一服务进程内共享临时配置。角色加载、后端选择及模型选择都读取该执行上下文。

保存的空验证命令也有意义：它表示这轮没有配置验证标准，不再在续跑时偷偷回读新环境中的命令。本轮 state 显式给出的 `test_command` 仍优先；既有接口明确修改 Run 角色模型或工具选择的能力仍保留。

### 4.3 历史记录缺少新字段时，查询与执行分别处理

不能凭旧记录中的 workflow ID 推断当时的完整流程定义。当前策略是：

- 查询、停止和删除历史记录仍可使用原检查点，不为了查看状态而强行编译最新 YAML。
- 对带 workflow ID、但没有 `workflow_definition` 的历史 Run，恢复前调用 `_require_resume_definition` 明确拒绝。
- HITL 提交等入口先检查恢复条件，再写入决定或审计字段，避免拒绝续跑却已修改批准记录。

`test_legacy_selected_run_is_readable_but_not_resumable` 验证状态仍可读、提交被拒绝且 baseline log 没有新增批准。此兼容策略针对所选 YAML 流程；并未给所有历史默认 Python 图增加版本兼容校验。

### 4.4 缓存与状态摘要同步调整

删除 Run 后同时移除 `_graphs[thread_id]`，防止检查点已删除而服务仍持有旧编译图。状态 API 的 `_public_values` 排除新增加的大块 `workflow_definition` 和 `config_snapshot_effective`，避免角色正文及完整定义随着普通轮询重复返回；持久化快照本身仍留在检查点中。

这不是全量字段脱敏措施。原有配置快照字段和其他返回值没有因此获得统一的敏感信息分类与访问控制。

## 5. 验证结果与成本记录

实现见 [command.py](../../src/geni_studio/verification/command.py)、[acceptance.py](../../src/geni_studio/verification/acceptance.py)，接入点在默认图和所选流程的活动节点。

### 5.1 实际测试结果不能沿用旧状态或只相信报告文本

原默认测试节点以 `state.test_status or pass` 开始，命令失败时才赋 fail。上一次测试失败后，即使修复后的命令退出码为 0，状态仍可能停在 fail；反过来，没有验证命令时真实后端也可能保留默认 pass。

新增 `verified_report` 统一计算当前验证结果：

| 本次情况 | 结果 | 证据处理 |
|---|---|---|
| 验证命令退出码 0 | pass | 把本次命令输出追加到报告 |
| 验证命令退出码非 0 | fail | 追加失败命令输出 |
| 命令不合法、超时、启动失败或相关参数错误 | fail | 记录失败异常类型，不把异常当作成功返回 |
| 没有命令，实际 tester 后端为 Stub | 使用模拟状态 | 明确追加“模拟验证，未执行测试命令” |
| 没有命令，实际 tester 后端为真实后端 | fail | 明确缺少机器验证证据 |

判断依据是 tester 的实际角色后端，不能仅看全局后端；因此全局 Stub、tester 单独选择 Codex 的混合配置不会被当成模拟验证。

命令运行仍使用既有工作目录和命令约束，本次没有新建一套命令沙箱。退出码 0 证明指定命令成功，不自动证明测试覆盖充分，甚至不自动证明发现了非零数量的测试。

**验证。** `test_machine_evidence_controls_test_outcome` 覆盖旧 fail 被当前成功替换、命令失败不能被报告里的 pass 掩盖、真实后端缺少命令判失败；真实开发闭环实际生成文件并执行 unittest。

### 5.2 YAML 流程测试活动绕过验证，QA 可能覆盖失败

原所选 YAML 流程的普通活动只调用角色并写产物，没有复用默认图的命令验证。现在对 `role=tester` 且输出包含 `test_report` 的活动调用同一个 `verified_report`。

失败时，如果活动配置了 `returns_to`，在正文追加 `STATUS: fail`，复用既有回退计数和升级逻辑；没有回退去向则抛异常中断，不能继续执行下游交付。这个抛异常发生在活动状态更新返回前，因此不能保证附加后的失败报告已经作为产物写入检查点，日志与异常仍是排查入口。

该改动没有把所有自定义活动统一变成质量门禁，也没有清除模型正文自身已有的 `STATUS: fail`。即使命令成功，原有报告失败标记仍可能触发已配置的回退；不要将其描述成“退出码是整个工作流唯一的放行条件”。

默认 QA 同时增加已知失败检查：如果 `test_status == fail`，不能因模型报告或验收编号检查看似正常而把 QA 状态恢复为 pass。

### 5.3 AC 编号用子串匹配，误认为已经覆盖

原逻辑检查 `ac in evidence`。需求包含 `AC-1`，证据只提到 `AC-10` 时，也会判定 `AC-1` 已出现。

当前对证据使用相同 AC 正则提取完整编号，转换为集合后逐一比较。回归用例要求 `AC-1 AC-10` 对照仅有 `AC-10` 的证据时，缺失列表包含 `AC-1`。

这里只修复编号识别；报告中出现某个编号，不等同于对应测试实际通过。语义证据绑定仍未实现。

### 5.4 相同用量的不同调用被去重，成本漏记

原 `_append_costs` 检查成本行是否已经出现在 prior 中。两次独立调用如果角色、模型和 token 数相同，后一次会被视为重复而丢弃；相同的 Stub 成本行也有同样问题。

当前按本次调用批次追加全部记录，不以文本相等判重。`test_equal_cost_lines_from_separate_calls_are_preserved` 连续追加相同用量行，确认两条都存在。

这没有实现调用 ID 级别的账务幂等。失败、停止或图执行异常时，部分用量仍可能没有追加到 Run 账本；有 token 也不等于已经取得准确费用。该账本用于运行观察，不替代供应商账单。

## 6. 验证依据与结果

### 6.1 环境、结果与证据口径

修复时的环境为 Python 3.12.14、`openai-codex` 0.167.0、LangGraph 1.2.20。真实 SDK 调用复用本机已有 ChatGPT 登录；没有配置或发送飞书消息，也没有在交付记录中输出密钥。

| 检查 | 已记录结果 | 能说明什么 |
|---|---|---|
| 修改前全量 pytest | 245 passed | 基线已有测试通过，不能覆盖此次发现的全部故障 |
| 修改后全量 pytest | **276 passed，3 skipped，14.19 秒** | 已有回归及新增确定性测试通过；3 项跳过是显式启用的真实 SDK 用例 |
| `ruff check src tests` | 通过 | 本轮代码静态规则检查通过 |
| JavaScript 语法检查与 Node 行为回归 | 通过 | 配置脚本可解析，指定保存/迁移场景通过 |
| `git diff --check` | 通过 | 修改的空白格式检查通过 |
| 真实 SDK 专项 | 下列三项分别实际通过 | 结果独立于默认跳过的全量回归统计 |

以上运行结果来自最初源码修复阶段的日志；后续分支合并的重新验证单独记录在 §6.4，不把文档校验记作 pytest 或模型执行。

### 6.2 真实 SDK 执行了什么

可复现用例保存在 [test_codex_live.py](../../tests/test_codex_live.py)。

| 用例 | 实际操作与断言 | 覆盖边界 |
|---|---|---|
| `test_live_codex_resume` | 第一次要求记住 `ORBIT_71832` 并返回 SAVED；第二个后端实例不重发该值，要求从上一消息回忆。检查返回值、同一 SDK thread ID、两次日志及用量 | 跨实例和跨客户端恢复；没有杀掉整个服务进程 |
| `test_live_workflow_writes_runs_tests_and_waits_for_human` | 在临时 Git 工作树生成 `sdk_smoke.py` 和 unittest；开发、测试角色实际调用 Codex，工厂另行执行测试命令。检查文件存在、报告 `exit=0`/OK、Codex 成本行，等待人工后由测试代码提交批准，最终 completed | 覆盖 SDK、角色入口、工作区、验证命令、图与服务层关卡；未覆盖可视化编辑器或浏览器点击 |
| `test_live_codex_stop_interrupts_active_command` | 请求执行等待命令，观察真实 `commandExecution` 开始，再发停止并检查 `RunStopped` | 运行控制与 SDK 停止适配；不是所有外部副作用的撤销测试 |

在正式专项用例之前，还执行过最小 SDK 请求，得到 `SDK_BASELINE_OK` 和 completed 终态，并核对了真实 `ThreadTokenUsage.last` 结构。开发闭环的实际输出显示正数、负数和零对应的 3 个 unittest 通过；其自动断言检查的是输出与退出码，不应扩大为测试覆盖率保证。

一次复测中，恢复测试的两个模型回答都正确，但测试共用旧日志目录，断言“两条日志”时实际读到四条而失败。随后将该测试的日志根目录隔离到临时目录，并重新验证通过（1 passed，14.48 秒）。该次复测中的开发闭环和停止用例均通过。因此这里记录的是三项分别有通过证据，不声称存在一次全新的“三项同时全部通过”日志。

### 6.3 确定性回归与实现位置的对应

| 修复主题 | 主要证据文件与用例 |
|---|---|
| SDK 终态、模型 ID、用量、沙箱、清理、超时、线程恢复 | [test_codex_backend.py](../../tests/test_codex_backend.py)；使用真实 SDK 数据类型和替身客户端 |
| 不等长并行、局部输入、定义不被编译修改 | [test_runtime_correctness.py](../../tests/test_runtime_correctness.py) 的 `test_unequal_parallel_branches_wait_and_read_local_outputs` |
| 拒绝复杂并行 | 同文件 `test_reject_unsupported_parallel`；[test_subgraph_parallel.py](../../tests/test_subgraph_parallel.py) 中内置整网流程预期拒绝 |
| 暂停保留结果、错误不被吞掉 | `test_pause_after_completed_call_keeps_node_output`、`test_pause_does_not_hide_real_exception`；既有 HITL 测试 |
| 同 Run 互斥和查询不误标中断 | `test_reject_concurrent_hitl_for_same_run`、`test_observation_does_not_mark_in_progress_mutation_interrupted` |
| 快照恢复和历史只读兼容 | `test_restart_uses_saved_workflow_not_modified_file`、`test_legacy_selected_run_is_readable_but_not_resumable` |
| 无明确批准不得过关 | `test_gate_never_implicitly_approves`，既有 PM/HITL 回归 |
| 命令结果、AC 完整编号、成本重复值 | `test_machine_evidence_controls_test_outcome`、`test_acceptance_ids_do_not_match_prefixes`、`test_equal_cost_lines_from_separate_calls_are_preserved` |
| 后端不隐式降级、配置反映实际环境 | [test_backends.py](../../tests/test_backends.py)、[test_config_web.py](../../tests/test_config_web.py) 及 SDK 测试 |
| 页面保存异常和模型迁移 | [config_runtime_regression.cjs](../../tests/config_runtime_regression.cjs)，通过 pytest 包装用例执行 |
| 探测不破坏文件、Key 失败不回显 | `test_workspace_probe_does_not_overwrite_existing_file`、`test_api_key_probe_does_not_change_local_sdk_login` |

用例名称不替代实际覆盖范围：例如带有 restart 名称的测试使用同一个 MemorySaver 重建服务对象，带有 HITL 名称的并发测试验证装饰器，而不是完整的多进程服务。没有专门回归或真实故障注入的机制，在各节中按实现说明记录。

### 6.4 合并上游更新后的适配与回归

2026-11-10，将基于 `5a55b33` 的 stash 合并到 `4389ea4`，保留上游 `79ccd8a` 的统一 API 错误展示、页面交互和 Web UI skill，以及 `4389ea4` 的本地项目、流程忽略规则。原 stash 保留，未创建提交。

- `config.js` 同时保留上游 `geniApi` 错误处理和本次模型隔离、保存异常恢复、异步响应保护；两个页面入口同步更新脚本版本参数，避免浏览器复用旧缓存。
- 保留 stash 中示例项目的配置更新：`profile_id` 从不存在的 `example_overlay_v1` 改为内置 `factory_default`，修复启动时提示没有流程的问题；`max_dev_retries` 为 3，相应更新配置摘要和运行状态的三个测试断言。
- Codex 替身客户端测试清除环境中的 `GENI_STUDIO_CODEX_MODEL` 和 `GENI_STUDIO_DEFAULT_MODEL`，避免本机配置使“未指定模型时沿用 SDK 默认值”的测试失败。仅隔离测试环境，不修改实际模型选择逻辑。

合并后首次全量回归发现上述三个旧重试次数断言和一个模型环境污染问题；适配后重新运行得到 **276 passed、3 skipped，14.14 秒**。`ruff check src tests`、配置脚本语法检查、Node 行为回归与 `git diff --check` 均通过。本次未重新调用真实 Codex 服务，3 项真实 SDK 用例按默认策略跳过，先前执行证据仍见 §6.2。

### 6.5 Rebase 到运行页更新后的兼容处理

随后将本次修复提交 rebase 到 `eb35184`，处理运行服务和两个页面入口的冲突：

- 保留上游 `_prepare_start`、后台 `enqueue_start`、临时状态响应和启动失败记录。配置快照在共同的 `_prepare_start` 中生成，同步与后台启动均通过已有的 `_invoke` 并发保护和运行配置上下文执行。
- 将 `@run_mutation` 保留在 `set_node_tools` 上，没有误移到新增的启动或查询方法；保留查询阶段的 `is_starting` 检查与本次观察互斥逻辑。
- `enqueue_start` 的返回标注改为实际使用的 `(thread_id, initial)` 元组；后台线程的异常捕获保留，并说明其记录失败供查询的用途。
- 两个页面入口使用新的 `config.js` 缓存版本，保留上游 `workflow.js` 的删除功能版本及运行页交互。
- 本次待 rebase 提交没有包含 §6.4 当时工作区中的示例项目配置修改；仓库示例仍为 `example_overlay_v1`、重试上限 5。因此三个测试恢复为与仓库配置一致的上限 5。示例项目的无效流程引用不属于本次冲突修复，仍需选定有效流程后使用。

新增后台启动成功和失败两项回归，验证启动标记清理、失败记录、临时响应不暴露内部配置快照，以及后台执行使用启动时冻结的模型配置。最终全量回归 **280 passed、3 skipped，15.96 秒**；Ruff、JavaScript 语法检查、配置页 Node 回归及差异空白检查通过。真实 Codex 服务未在这次 rebase 验证中调用。

## 7. 兼容性变化、剩余边界与文档归并

### 7.1 直接影响既有行为的变化

| 旧行为 | 当前行为 | 原因 |
|---|---|---|
| 后端不可用也可能运行 Stub | 明确报错，只有显式 Stub 才模拟 | 防止占位产物冒充真实结果 |
| 关卡没有决定也可能通过 | 缺失或非法决定报错，消费后清除 | 防止隐式批准与旧决定复用 |
| 暂停可以丢弃当前已完成调用 | 以节点为边界，保留正常结束的结果 | 避免恢复后重复执行 |
| 复杂并行定义可进入执行 | 不支持的结构或工作区并行写入明确拒绝 | 当前状态和工作区模型不足以保证正确性 |
| 旧 YAML Run 用新文件续跑 | 缺少定义快照时拒绝恢复，仍可查看和管理 | 避免检查点与图定义不一致 |
| 真实测试没命令也可能 pass | 判失败，要求机器验证证据 | 防止报告文本代替验证 |

### 7.2 本次没有实现的保证

- **副作用恢复。** 没有 operation ID、完成回执或事务性副作用记录。文件已修改但检查点未提交时崩溃，人工续跑仍可能重做；会话恢复不能代替节点操作幂等。
- **跨进程调度。** Run 锁是进程内 RLock。Codex 会话文件的 `flock` 只保护特定会话映射和调用，不会让整个图获得多 worker 或多主机一致性；该实现还依赖 Unix `fcntl`。
- **旧 HITL 请求。** 仍无持久待办 ID 与幂等回执。互斥防止同时修改，不识别先后到达的旧卡片或重复审批是否属于当前待办。
- **全面冻结。** 没有冻结 Python 节点实现、第三方库、SDK 外部规则/Skill/MCP、远程模板及默认 Python 图的全部模板内容，没有跨版本兼容性指纹。
- **所有后端会话恢复。** 本次 Codex 使用持久 thread ID 解决新实例丢历史；Cursor 的实例缓存并未增加同等跨实例/跨进程恢复机制。
- **完整超时和撤销。** SDK 客户端构造、初始化和会话锁等待不在调用计时器内。停止已验证能结束本轮测试中的 SDK 调用，不保证撤销已经发生的文件、子进程或远程副作用。
- **完整成本与日志。** 失败/中断调用或异常批次可能缺失用量；日志有既有截断限制，摘要不是原始协议归档，也不是全面脱敏系统。
- **发布和语义验收。** 自定义流程仍需配置测试活动及失败路径，未增加全局强制发布门禁。命令成功、报告出现 AC 编号都不能单独证明所有验收条件成立。
- **全部认证路径。** 真实专项使用本机 ChatGPT 登录，未验证 API Key 推理、所有供应商目录策略、NPU 工具链或长时复杂任务。正常 SDK Key 登录仍可能影响本机认证缓存。
- **配置事务与完整 UI 测试。** 页面逐项保存仍可部分成功，现有前端回归是 Node 函数测试，不是浏览器全流程自动化。

这些边界用于限定本轮修复的保证，不应在后续描述中写成已完成能力。

### 7.3 配套文件与维护范围

新增运行支撑模块是 `backends/runtime.py` 和 `hitl/transaction.py`；其余行为修改分布在前文链接的后端、配置、流程、HITL 和验证文件。新增回归位于 `tests/test_runtime_correctness.py`、`tests/test_codex_live.py` 与前端回归脚本，原 SDK 测试已重构为真实类型契约测试。

[pyproject.toml](../../pyproject.toml) 固定已验证的 Codex SDK 版本；[.gitignore](../../.gitignore) 排除工厂 `.geni_studio/` 运行数据。[README](../../README.md) 和[安装文档](../install.md) 同步调用方式及后端默认行为，[路线图](../plans/roadmap.md) 撤回复杂并行“已完成”的表述。没有新增 reviews 文档或独立 Codex 使用说明。

角色 Markdown 没有修改，默认 Python 图没有重排；其中的修改限于快照状态字段、暂停保护与验证状态判定。[ADR 0008](0008-codex-sdk-backend.md) 保持原样，本文件统一记录其后的正确性修复和验证边界。
