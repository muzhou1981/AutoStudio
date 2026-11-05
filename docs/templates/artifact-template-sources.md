# 产物模板 · GitHub 来源调研

本文档为各角色 **outputs** 在 GitHub 上可复用的 Markdown 模板调研结果，供 `templates/artifacts/` 落地时参考。**未在仓库内拷贝正文**；合入前请自行核对各上游仓库的 License，并按 `config_plan` 做字段裁剪（`AC-n`、`TASK-n`、`phase` 等工厂约定）。

**图例**

| 匹配度 | 含义 |
|--------|------|
| **高** | 结构可直接作 `templates/artifacts/<name>.md` 初稿，少量改 front matter |
| **中** | 需合并多份模板或删减章节后使用 |
| **低** | 仅作段落参考，建议 **手工编写** 工厂专用模板 |

---

## 项目经理

### `requirement_spec`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| jam01/SRS-Template | https://github.com/jam01/SRS-Template | IEEE 830 / ISO 29148 取向的 Markdown SRS，含范围、可验证需求、追溯 |
| vibeflow `srs-template.md` | https://github.com/ttttstc/vibeflow/blob/620bd514/docs/templates/srs-template.md | FR + Given/When/Then 验收、追溯矩阵、Mermaid 流程 |
| awesome-copilot `create-specification` | https://github.com/github/awesome-copilot/blob/main/skills/create-specification/SKILL.md | 带 YAML front matter 的规格结构，**AC-001** 编号风格与角色定义一致 |
| philipz `requirements-engineer/TEMPLATES.md` | https://github.com/philipz/skills/blob/main/skills/requirements-engineer/TEMPLATES.md | 需求表 + 用户故事 + 验收块，可作附录 |

**适配**：保留「范围内/外、验收标准编号、待确认问题」；粗估/正式版用 front matter `phase: draft|confirmed`。

### `delivery_report`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| NahuelGiudizi `QA_SIGNOFF` + execution report | https://github.com/NahuelGiudizi/qa-deliverables | 发布清单与签收流程，可拆「验收对照表」一节 |
| Aniekanetim `release-signoff.md` | https://github.com/Aniekanetim/AI-Agent-Software-QA/blob/main/QA/Quality%20assurance/release-signoff.md | 交付包结构：测试完成、风险、签收、运维交接 |

**需手工补充**：逐条 `AC-n` 结论 + 证据指针（`test_report` / `qa_report` 条目 id）、预算执行摘要（引用 `cost_report` 快照）。无单一「交付报告」模板。

---

## 测试工程师

### `testability_review`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| （无专用模板） | — | 可参考 SRS 中「验收标准」章节做 **按 AC-n 的评审表** |

**建议列**：`AC-n` | 问题类型（不可判定/含糊/缺边界）| 改写建议 | 状态。

### `test_cases`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| fugazi `test-cases.csv` + ISTQB skill | https://github.com/fugazi/test-automation-skills-agents/tree/main/skills/qa-manual-istqb | 用例库 + 追溯；可改为 Markdown 表 |
| jmagly `test-documenter` 内 TC 规格 | https://github.com/jmagly/aiwg/blob/main/plugins/sdlc/agents/test-documenter.md | **TC-xxx**、步骤表、前置、期望，与角色编号一致 |

### `test_report`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| fugazi `test-summary-report.md` | https://github.com/fugazi/test-automation-skills-agents/tree/main/skills/qa-manual-istqb | 周期总结与签收取向 |
| NahuelGiudizi `TEST_EXECUTION_REPORT_TEMPLATE.md` | https://github.com/NahuelGiudizi/qa-deliverables | 执行报告、环境、汇总 |
| fugazi `bug-report.md` | 同上仓库 `docs/` | **DEF-n** 缺陷块可嵌入 `test_report` |

---

## UX / UI / 美工

### `ux_spec`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| jmagly `sdlc-complete/templates/ux` | https://github.com/jmagly/aiwg/tree/main/agentic/code/frameworks/sdlc-complete/templates/ux | 用户旅程、线框规格、可追溯 UC |
| Agile-V `ux-spec-author` DESIGN.md 片段 | https://github.com/Agile-V/agile_v_skills/blob/main/ux-spec-author/SKILL.md | **UF-xxxx** 流、状态表、无障碍 |
| bmad-skills `user-flow.template.md` | https://github.com/aj-geddes/claude-code-bmad-skills/tree/b5c64038/bmad-skills/ux-designer/templates | 用户流 + ASCII 线框说明 |
| JimmySadek/wireframe-doc `spec-template.md` | https://github.com/JimmySadek/wireframe-doc | 线框文档 front matter（偏展示，可作 FLOW/WF 附录） |

**适配**：统一 **FLOW-n / WF-n**，每条体验要求映射 **AC-n**。

### `ui_spec`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| jmagly `wireframe-specification-template.md` | 见 ux 目录同上 | 布局、组件清单、状态、无障碍 |
| google-labs-code `design.md` spec | https://github.com/google-labs-code/design.md/blob/main/docs/spec.md | **DESIGN.md**：令牌 YAML + 组件；适合 **CMP-n / SCR-n** |
| aiwg wireframe 模板 | 同上 jmagly | 实现交接、响应式、验证规则 |

**说明**：Primer 的 [DESIGN_TOKENS_GUIDE](https://github.com/primer/primitives/blob/main/DESIGN_TOKENS_GUIDE.md) 可作令牌语义参考，非完整 ui_spec。

### `visual_assets`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| （无标准「资源清单」模板） | — | 可参考各平台 **asset catalog** 自建表：**AST-n**、路径、格式、尺寸、映射 **CMP/SCR** |

---

## 架构师

### `architecture_design`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| foxcool/architecture-doc-template | https://github.com/foxcool/architecture-doc-template | arc42 + C4，章节全 |
| NetworkedAssets/arc42-in-markdown-template | https://github.com/NetworkedAssets/arc42-in-markdown-template | 单文件 arc42 Markdown |
| gotalab/cc-sdd `specs/design.md` | https://github.com/gotalab/cc-sdd/blob/fd3fc86c/tools/cc-sdd/templates/shared/settings/templates/specs/design.md | 实现向设计、追溯、边界 |
| wicked-garden `architecture-template-design.md` | https://github.com/mikeparcewski/wicked-garden/blob/main/skills/engineering/architecture/refs/architecture-template-design.md | 组件、数据、部署 |

**适配**：设计项 **AD-n** 映射 **AC-n**；重大决策可链到 ADR（见下）。

### `task_plan`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| ilandahan `task-breakdown-template.md` | https://github.com/ilandahan/aid/blob/main/skills/aid-impl-plan/templates/task-breakdown-template.md | **TASK-n**、依赖、验收、测试 |
| github/awesome-copilot implementation plan | https://github.com/github/awesome-copilot/blob/main/skills/create-implementation-plan/SKILL.md | 分阶段任务表 |
| github/awesome-copilot specification TASK 表 | 同上 create-specification | 与需求 **REQ/AC** 同页时的任务表风格 |

---

## 程序员

### `code_change`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| pinecone-io `.github/pull_request_template.md` | https://github.com/pinecone-io/.github/blob/main/.github/pull_request_template.md | Problem / Solution / Test Plan |
| TalAter/open-source-templates PR 模板 | https://github.com/TalAter/open-source-templates/blob/master/PULL_REQUEST_TEMPLATE.md | 变更说明 + 测试 + Checklist |

**需手工补充**：**TASK-n**、**AC-n**、本地验证命令输出、与 `ui_spec` 的 **SCR/CMP** 引用（界面任务）。

---

## 代码评审

### `review_report`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| projekta2 `pr-review-checklist-template.md` | https://github.com/projekta2/pr-review-canvas/blob/main/checklists/pr-review-checklist-template.md | 分级检查项，可映射 **阻断/建议/细节** |
| awesome-skills `review-checklist.md` | https://github.com/awesome-skills/code-review-skill/blob/main/assets/review-checklist.md | 严重性标签与 `[blocking]` 语义 |
| mshykov/local-review `CHECKLIST.md` | https://github.com/mshykov/local-review/blob/main/CHECKLIST.md | 可执行评审项 |

**需手工补充**：总体结论（通过/需修改）、**RV-n** 意见表、与 **task_plan / ui_spec** 对照节。

---

## QA

### `qa_report`（高）

| 来源 | 链接 | 说明 |
|------|------|------|
| ITSalt/NaCl `qa-report-template.md` | https://github.com/ITSalt/NaCl/blob/main/nacl-tl-core/templates/qa-report-template.md | **AC 逐条 PASS/FAIL**、证据列、verdict |
| flamemida `acceptance-report.md` | https://github.com/flamemida/spec-dev/blob/main/skills/acceptance-qa/templates/acceptance-report.md | 多维度验收 + 需求覆盖表 |
| NahuelGiudizi `QA_SIGNOFF_TEMPLATE.md` | https://github.com/NahuelGiudizi/qa-deliverables | 发布签收 |

**需手工补充**：流程审计（`baseline_log`、评审闭环）专节——上游 **release-signoff** 有可借鉴段落。

---

## 财务

### `budget_plan` / `cost_report`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| （无 Agent/LLM 成本模板） | — | 常见为 spreadsheet；工厂需 **phase: rough|final|snapshot**、按角色/节点/模型拆分、链 `cost_ledger` |

**建议**：自建 Markdown 表 + 简短说明字段；可参考企业内部 FinOps 表格结构，GitHub 上无稳定对标。

---

## 配置管理员

### `config_plan`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| （无「单轮 config_plan」公开模板） | — | 需写：场景、分支/工作树、产物→模板路径、命名、基线点、`design_track` |

### `baseline_log`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| （无） | — | **追加式**登记：关卡/变更、批准依据、产物版本、关联 `change_request` |

### `config_baseline`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| NahuelGiudizi `RELEASE_CHECKLIST.md` | https://github.com/NahuelGiudizi/qa-deliverables | 发布物清单部分可借鉴 |
| release-signoff 交付包 | 见 QA Aniekanetim | 代码标签 + 文档版本清单 |

### `config_retro` / `config_proposals`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| Daizah `retrospective-template.md` | https://github.com/Daizah/pm-templates-toolkit/blob/main/closing/retrospective-template.md | 改进项 + 证据表；**config_retro** 需加「模板符合度打分」列 |
| （proposals） | — | 接近 **RFC**，见下 |

---

## 流程负责人

### `retro_report`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| Daizah retrospective | 同上 | Top 改进 + 行动项 |
| npow `sprint-retro/FORMAT.md` | https://github.com/npow/claude-skills/blob/main/sprint-retro/FORMAT.md | 数据驱动 retro 结构 |

**需手工补充**：流程分、各角色产物分、**Top3 有价值 / Top3 待改进**（与 `rubrics/` 对齐）、引用 `config_retro`。

### `process_proposals`（中）

| 来源 | 链接 | 说明 |
|------|------|------|
| appwrite `rfc-template.md` | https://github.com/appwrite/rfc/blob/main/rfc-template.md | 变更对象、设计、风险、测试 |
| InnerSourceCommons RFC | https://github.com/InnerSourceCommons/InnerSourcePatterns/blob/main/patterns/2-structured/templates/rfc.md | 动机、方案、取舍 |
| adr/madr | https://github.com/adr/madr/blob/main/template/adr-template.md | 仅适合 **小范围流程/技术决策**，非整图替换 |

---

## 共用：`change_request`（低 → 建议手工）

| 来源 | 链接 | 说明 |
|------|------|------|
| RFC 模板 | 见上 appwrite / InnerSource | 缺「目标产物、影响 AC、disposition（PM/架构师）」工厂字段 |

**建议字段**：`id`、`raised_by`、`target_artifact`、`reason`、`impacted_ac`、`recommended_owner`、`status`。

---

## 引擎级（非角色 outputs，模板可选）

| 产物 | 调研结论 |
|------|----------|
| `human_request` | 自由文本，无模板 |
| `cost_ledger` | 已落地 `templates/artifacts/cost_ledger.md`（追加式台账表） |
| `run_record` | 已落地 `templates/artifacts/run_record.md`（Data coverage 索引表） |

---

## 建议落地顺序

1. **高匹配**：`requirement_spec`、`test_cases`、`test_report`、`architecture_design`、`task_plan`、`qa_report`
2. **中匹配**：`ux_spec`、`ui_spec`、`code_change`、`review_report`、`retro_report` / proposals 基底
3. **手工**：`testability_review`、`change_request`、`config_plan`、`baseline_log`、`budget_plan`、`cost_report`、`cost_ledger`、`delivery_report`（合稿）、`visual_assets`、`config_plan` 相关、`run_record`

在 `templates/artifacts/` 中为每项增加 YAML front matter（`artifact`、`producer`、`consumers`、`phase` 若适用）后，由 `config_manager` 在 `config_plan` 中引用路径。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-11-05 | 初版：GitHub 公开模板调研，供手工补全与拷贝 |
| 2026-11-05 | 已落地 `templates/artifacts/*.md`（每产物 1 模板）；`requirement_spec` 采用 vibeflow SRS（jam01/SRS-Template  raw 不可用）；无对标项为工厂自建骨架 |
