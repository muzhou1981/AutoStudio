---
name: geni-studio-web-ui
description: >-
  Optimizes, builds, or reviews GeniStudio Web UI in Operate mode: hitl.html SPA
  (run, project, workflow, role, config), config.js, workflow.js, role.js,
  Web Awesome forms, field validation, API error copy, and list sync after
  navigation. Use when the user asks for UI/UX polish, config or run page
  behavior, dropdown empty, or model picker issues. Authoritative spec is
  docs/design/ui-ux.md.
---

# GeniStudio Web UI 优化

面向 **Operate** 模式（完成任务的工厂界面），不是营销页。模式与检查项借鉴自 GitHub 上的 dashboard frontend 与 polish 类 Skill，见 [SOURCES.md](SOURCES.md)。

## 必读（本仓库）

1. [`docs/design/ui-ux.md`](../../../docs/design/ui-ux.md) — 信息架构、六页职责、文案与交互约束。
2. [`AGENTS.md`](../../../AGENTS.md) — 改 `src/` 后运行 `pytest` 与 `ruff check`。
3. 涉及产品决策时对照 [`docs/requirements.md`](../../../docs/requirements.md)。

## 代码地图

| 区域 | 主要文件 |
|------|----------|
| 壳与路由 | `src/geni_studio/web/static/hitl.html`（`applyRoute`、`data-route`） |
| 配置 / 项目 | `src/geni_studio/web/static/config.js`、`api-utils.js` |
| 流程 | `src/geni_studio/web/static/workflow.js` |
| 角色 | `src/geni_studio/web/static/role.js` |
| 样式 | `hitl.css`、`shared.css`（`config-form-half`、`inline-error`） |
| 配置 API | `src/geni_studio/web/config_routes.py` |
| UI 回归 | `tests/test_implemented_round.py`、`tests/test_config_web.py` |

后端默认 `127.0.0.1:8765`；新 API 需重启 `geni-studio-web` 后浏览器强刷。

## 开工前用书面语写四行（改自 gram frontend「Frame the job」）

```
谁：      工厂决策者正在哪一页、要完成什么（运行 / 项目 / 配置…）
任务：    一句话动词目标，不写 API 字段名
流程：    1… 2… 3… 最少步骤
落点：    改动落在哪条路由、哪个 `func-region`
```

若任务与 `ui-ux.md` 冲突，先指出冲突并请用户确认，再改代码。

## Operate 原则（本地化）

1. **先选后编**：项目、流程等用下拉选择即生效时，不保留多余的「打开」类按钮。
2. **表单不写回未展示字段**：例如不再在 UI 编辑 `remote_url` 时，PUT 须用 `exclude_unset` 或等价逻辑，避免清空 YAML 已有键。
3. **跨页状态同步**：配置页改动的列表（项目、后端模型）在进入运行页或保存后须刷新；勿假设单页 init 一次即可。
4. **错误给人看**：`formatApiDetail` / `apiErrorMessage` 处理 422 数组 `detail`；控件旁 `inline-error` 优先于页底总报错。
5. **最小 diff**：只改与任务相关的 HTML/CSS/JS；中文书面语；不整篇重排无关章节。

## 实现要点

### Web Awesome

- 动态填充 `wa-select` 前 `await customElements.whenDefined("wa-select")` / `wa-option`。
- 选项与 `config.js` 中 `waOption` / `fillOneWorkflowSelect` 保持一致。
- 只读工作区用目录选择器 + 只读 `wa-input`，与 `dirPicker` 复用。

### 测试

- 页面结构断言加在 `tests/test_implemented_round.py`（读取 `hitl.html` 字符串）。
- 配置 API 行为加在 `tests/test_config_web.py`。

## 交付前

阅读 [reference/polish-checklist.md](reference/polish-checklist.md) 中与本改动相关的条目；运行 `pytest` 与 `ruff check`。

## 上游与许可

见 [SOURCES.md](SOURCES.md)。
