# Operate 界面抛光清单（摘自 impeccable `polish.md`，已本地化）

交付前对照本清单检查**本次改动触及**的控件与流程。

## 表单

- 标签与 hint 使用书面语，避免口语与未定义缩写。
- 必填与可空字段在文案中说明清楚；错误显示在控件附近（`inline-error` 或 `projectError`），不用 `[object Object]`。
- 校验时机一致：失焦或保存前统一走 `/api/config/projects/field-check` 或与后端相同的规则。
- Tab 顺序符合视觉顺序；destructive 操作（删除）需一次明确确认。

## 状态

- 加载：`wa-button` 的 `loading` / `disabled` 成对恢复。
- 空：空列表、空项目、无流程时有引导文案，不只静默空白。
- 错误：FastAPI `detail` 为数组时用 `formatApiDetail` 解析后再展示。

## 布局

- `config-form-half` 控件宽度一致（约 50%）；勿让 `dir-path-row` 里的输入框撑满整行。
- `wa-select` 放在 `overflow: auto` 容器内时优先 `placement="bottom-start"`，或放宽容器 `overflow`，避免下拉无法点击。
- 静态资源改动后递增 `config.js` / `workflow.js` 的 `?v=` 查询参数；**新增 REST 路由须重启 `geni-studio-web`**。

## SPA 数据同步

- 项目列表：运行页进入时调用 `loadRunConfigOptions`；配置页创建/删除后调用同一刷新逻辑。
- 角色模型：`refreshRunRoleModels` 之前 `await syncRunBackendModels()`，保证 `window.__backendModels` 与 `.env` 生效后端一致。
