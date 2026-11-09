# 0002 · 场景配置、项目配置与流程/模板裁剪

- 状态：已接受（M2 核心：RunContext、模板决议、profile 裁剪已落地；Web CRUD 未做）
- 日期：2026-11-05

## 背景

需求要求：内置多类**场景**（流程、模板、工具、规范），且均可扩展；Web 入口需支持**基础配置**与**项目级配置**。当前已有工厂默认图 `default`、默认模板 `templates/artifacts/`，以及图内 **`design_track`** 条件分支原型，但尚未形成统一的「解析—合并—生效」机制。

## 决策

采用 **四层配置栈**，由引擎在**每次 Run 启动时**解析一次，写入运行上下文 `RunContext`；**配置管理员**在 `config_plan` 中登记本轮生效结果（路径、裁剪项、workflow profile），供 QA 与复盘核对。

| 层级 | 存放位置 | 作用 |
|------|----------|------|
| L0 工厂默认 | `templates/artifacts/`、`src/geni_studio/workflows/default.py`、`roles/` | 全厂基线 |
| L1 场景 | `scenarios/<scenario_key>/scenario.yaml`（+ 可选 `templates/`、`workflow_profile.yaml`） | 一类项目的 reusable 预设（算子、Web、CLI 等） |
| L2 项目 | `projects/<project_id>/project.yaml`（+ 可选 `templates/`）；或目标仓库 `.geni_studio/project.yaml` | 具体目标软件/仓库的覆盖 |
| L3 单次运行 | Run 输入、`design_track_enabled`、人工关卡后的 state 补丁 | 本轮例外 |

**合并规则**：同名字段 **L3 > L2 > L1 > L0**；未声明则继承下层。禁止项目配置修改 `roles/` 正文（走 `change_request` + 流程负责人）；项目仅覆盖**场景、模板路径、流程 profile、工具列表、预算参数**。

## 模板：如何实现「单独配置 / 裁剪」

### 解析（M2 最小实现）

每个产物名（如 `requirement_spec`）在合并后的配置中对应：

```yaml
artifacts:
  requirement_spec:
    template_path: ""          # 最终选用的单个 Markdown 文件
    omit_sections: []          # 可选：按二级标题名省略（Agent 填表时不生成该节）
    required_sections: []      # 可选：校验用，缺则 config_manager 告警
```

**`template_path` 决议算法**（首个非空生效）：

1. `project.yaml` → `artifacts.<name>.template_path`
2. 否则 `scenarios/<key>/templates/<name>.md` 若文件存在
3. 否则 `templates/artifacts/<name>.md`

不做复杂 Markdown 合并；**裁剪**优先用 `omit_sections`，或由场景/项目提供**整文件替换**的 `template_path`。若未来需要「默认 + 增量段落」，再引入 `overlay_path`（ADR 修订），M2 不实现。

### 运行时如何使用

1. 引擎在调用某角色 Agent 前：`template = load(resolved_path)`，从 profile 去掉 `omit_sections` 对应章节（按 `##` 标题匹配），注入 prompt：`roles/<name>/role.md` + 模板正文 + 已有产物上下文。
2. 产出写回路径由 `config_plan.storage` 规定（与模板解析独立）。

## 流程：如何实现「单独配置 / 裁剪」

与 ADR 0001 一致：**图结构仍以 Python 为源码**；裁剪不默认「每项目一份独立 `.py` 图」，而用 **Workflow Profile** 驱动**同一张编译图**上的路由与节点是否执行。

### Workflow Profile（建议 schema）

```yaml
# scenarios/<key>/workflow_profile.yaml 或 project.yaml 内 workflow 段
workflow:
  graph_id: default              # langgraph.json 中的图名
  profile_id: npu_operator_v1

  # 二选一风格（实现时只支持一种即可）
  skip_nodes: [ux_designer, ui_designer, visual_designer]
  # enabled_nodes: [project_manager_draft, tester_testability, ...]  # 显式白名单，慎用

  gates:
    gate_requirement_confirm: true
    gate_architecture_review: true
    gate_final_delivery: true

  features:
    design_track: false          # 与 state.design_track_enabled 默认一致
    finance_enabled: true

  limits:
    max_dev_retries: 3

  roles:
    developer:
      backend: cursor
      model: ...
      skills: []
      mcp: []
```

### 裁剪在引擎中的两种落地方式（分阶段）

| 阶段 | 做法 | 适用 |
|------|------|------|
| **M2-a** | 已有 **条件边**（如 `route_after_config_plan`）+ 将 `SCENARIO_KEYS_WITH_DESIGN_TRACK` 迁入 `scenario.yaml` 的 `features.design_track` | 设计链、少量开关 |
| **M2-b** | 每个节点入口调用 `RunContext.assert_node_enabled(name)`：若 profile 标记 skip，则 **no-op** 写 stub 日志并透传 state，**不调度 Agent** | 跳过整角色且不改图拓扑 |
| **M2-c** | Profile 生成 **路由表**（下一跳映射），在少数分叉点读取；或新增 `build_graph(profile)` 仅用于差异极大的场景 | 仅当 M2-b 不够且不愿维护多图 |

**原则**：关卡节点（`gate_*`）默认不可被项目静默关闭；若 `gates.*: false`，须 L3 显式人类批准并写入 `baseline_log`。

### 与 LangGraph / Studio 的关系

- `langgraph.json` 仍注册完整 `default` 图（便于 Studio 看全量拓扑）。
- 实际 Run 的 `configurable` 或 state 携带 `workflow_profile_id`；VizLang/Studio 调试时可手动设 `scenario_key` / `project_id` 测裁剪。

## 项目配置入口（Web 一期）

| 配置项 | 存储 | UI |
|--------|------|-----|
| 场景 | 选 `scenario_key` | 下拉 + 说明 |
| 项目 | `project_id` → `projects/<id>/project.yaml` | 项目表单或 YAML 编辑 |
| 模板覆盖 | `project.yaml` 的 `artifacts.*.template_path` | 可选上传/路径 |
| 流程裁剪 | `workflow.skip_nodes` / `features` | 高级选项或只读展示（由场景定） |
| 密钥 | 运行环境 / 用户密钥存储 | API key 页 |

Run 输入示例：

```json
{
  "human_request": "...",
  "project_id": "silu_mul",
  "scenario_key": "npu_operator",
  "design_track_enabled": false
}
```

## `config_plan` 的角色

配置管理员节点（或引擎在 `config_manager_plan` 之前）根据合并后的配置产出 **`config_plan` 结构化内容**（或 Markdown 实例），至少包含：

- 生效的 `scenario_key`、`project_id`、`workflow.profile_id`
- 每个产物的 `template_path` 与 `omit_sections`
- `skip_nodes` / `gates` / `design_track`
- 分支、工作树、产物落盘目录

QA 与复盘以 **`config_plan` + `baseline_log`** 审计「是否按项目约定执行」。

## 校验

启动 Run 前引擎须：

1. 解析 L1+L2，未知 `scenario_key` / `project_id` → 拒绝或回退 L0（产品决策：建议 **拒绝** 并提示创建项目配置）。
2. `skip_nodes` 中的名字须存在于 `default` 图；非法名 → 拒绝。
3. 角色 `capabilities` 与所选 backend 匹配（已有架构要求）。
4. 被 skip 的角色其 **outputs** 可为空；下游角色 **inputs** 若依赖缺失产物，profile 须同时 skip 下游或场景声明「可选输入」——M2 在 scenario.yaml 用 `artifacts_optional: [ux_spec, ui_spec]` 声明。

## 目录约定（新增）

```text
scenarios/
  <scenario_key>/
    scenario.yaml
    workflow_profile.yaml   # 可并入 scenario.yaml
    templates/              # 可选覆盖
projects/
  <project_id>/
    project.yaml
    templates/
```

目标仓库可选：`<target_repo>/.geni_studio/project.yaml` 指向 `project_id` 或内联 L2 片段（引擎合并时 L2 以工厂 `projects/` 为主，仓库内文件为补充，避免双源冲突——**M2 只支持工厂 `projects/` 单源**，仓库内仅放 pointer）。

## 不做什么（M2）

- 不做拖拽式流程编辑器。
- 不做 YAML 全图编译替代 Python（与 ADR 0001 冲突时，以 0001 为准）。项目已选择 `workflows/<id>/workflow.yaml` 时，改以 [ADR 0005](0005-selected-workflow-compiles-run-graph.md) 为准：当轮的图按该流程的节点编译。未选择流程时，本条仍然有效。
- 不做模板 Git 子模块自动同步（项目模板路径手动或 CI 拷贝）。

## 后续实现顺序（建议）

1. `RunContext` + 加载 `scenario.yaml` / `project.yaml`（ pydantic 或 dataclass）。
2. `resolve_template(artifact_name)` + 单元测试。
3. `resolve_design_track` 改为读 profile，删除硬编码 `SCENARIO_KEYS_WITH_DESIGN_TRACK`。
4. `assert_node_enabled` 包装各 Agent 节点（或统一 decorator）。
5. Web：项目 CRUD + Run 绑定 `project_id`。

## 与现有代码的对应

- 已有：`design_track_enabled`、`route_after_config_plan` → 读 `features.design_track`（`resolve_design_track`）。
- 已有：`templates/artifacts/*.md` → L0；`scenarios/npu_operator`、`scenarios/web_app`、`projects/_example` 示例。
- 已有：`src/geni_studio/config/`（`RunContext`、`resolve_template`、`skip_if_disabled`）。
- 待做：Web 项目 CRUD；节点内注入 `load_template_text` + 角色 Agent。
