# 0017 · 以异常类型决定 HTTP 状态码；状态展示与页面脚本独立成文件

- 状态：已实现
- 日期：2026-11-11
- 关联：[问题与改进方案](../plans/architecture-remediation.md) C13；补充 [0011](0011-run-executor-and-runtime-store.md) 的运行时拆分。

## 背景

Web 路由通过匹配错误文本（如 `"未知" in str(e)`、`startswith("流程不存在")`、`"不在 awaiting_human"`）决定返回 404、409 还是 400，改动提示文字就会改变接口语义。`hitl/service.py` 同时承担生命周期、HITL 与展示；`hitl.html` 含约 3200 行内联脚本，无法单独检查与缓存。

## 决定

1. **异常类型。** `hitl.service` 新增 `RunNotFound`（运行或草稿不存在）、`RunConflict`（与当前状态冲突，如确认名称不一致）及其子类 `NotAwaiting`（不在等待人决定）；`RunBusy` 改为 `RunConflict` 的子类。`config.context` 新增 `ConfigNotFound(ConfigError)`，用于未知场景、项目、流程与角色。
2. **统一映射。** `web/errors.py` 的 `status_for()` 规定：`RunNotFound`、`ConfigNotFound` 为 404，`RunConflict` 为 409，其余按路由给出的默认值（通常 400，运行控制类为 409）。路由统一写 `raise http_error(e, 默认值) from e`；应用另注册异常处理器，未被路由捕获的上述异常同样按类型返回。飞书回调以 `isinstance(e, NotAwaiting)` 判定过期卡片。
3. **展示层。** 轨道、阅读区、选项、公开字段与关卡超时提示移到 `hitl/presenter.py`，入口为 `status_payload(st, values)`；`GraphRunService.status_dict` 只补充停止、暂停与任务信息。展示层只读，不依赖服务对象。
4. **页面脚本。** `hitl.html` 的主脚本原样移到 `static/hitl.js`，在原位置以同步 `<script src>` 引入，执行顺序与全局作用域不变；页头主题初始化脚本仍保留内联，以免首屏闪烁。

## 后果

- 修改错误提示文字不再影响状态码；新增「不存在」类错误须抛出对应类型。
- 原先按文本被判为 404 而实际不属于「不存在」的情况不再出现；原有接口的状态码保持不变（由测试覆盖）。
- 读取页面源码断言前端行为的测试须同时读取 `hitl.js`。
