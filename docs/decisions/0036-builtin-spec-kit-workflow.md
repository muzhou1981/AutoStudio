# 0036 · 内置 Spec Kit 规格驱动开发流程

- 状态：已采纳
- 日期：2026-11-13

## 背景

人在编辑页搭了一份“spec-kit”流程（`workflow-2`），把规格与计划合在一步产出，没有任务拆分与一致性分析；所用模板一份来自中间件的规格模板，另一份是已填写的具体计划，不能作为通用模板。需要按 [github/spec-kit](https://github.com/github/spec-kit) 的方法提供一份内置流程。

spec-kit 的主线命令是 `specify → plan → tasks → implement`，官方 `workflows/speckit/workflow.yml` 在规格与方案之后各设一道人工审核；辅助命令有 `clarify`（最多 5 个澄清问题）、`checklist`（需求质量清单）、`analyze`（规格、方案、任务三者只读一致性分析）、`converge`（对照代码追加剩余任务）与 `constitution`（项目原则）。

## 决定

1. 新增内置流程 `workflows/spec_kit/`，标题“Spec Kit 规格驱动开发”，`builtin: true`，不能保存或删除，要改先复制。
2. 节点与 spec-kit 的对应：

   | 节点 | 角色 | 对应 |
   |---|---|---|
   | 起草规格 | 项目经理 | specify，规格末尾附最多 5 个待澄清问题与推荐答案 |
   | 审规格 | 人 | review-spec 与 clarify：不通过时附言作答，退回起草规格写回规格 |
   | 制定方案 | 架构师 | plan，含调研、数据模型、接口契约、快速验证 |
   | 拆分任务 | 架构师 | tasks |
   | 一致性分析 | 质量保证 | analyze；有严重问题判为不通过，回退到制定方案，最多 2 次 |
   | 审方案 | 人 | review-plan |
   | 实现 | 程序员 | implement |
   | 核对实现 | 测试工程师 | converge 加运行测试；有严重、高等级缺口或测试失败，回退到实现，最多 3 次 |
   | 验收 | 人 | 不通过时回到实现 |

3. 两道人工审核带决策项，汇总规则为“由人决定”：决策项把 `checklist` 落到人工核对上，不强制全部通过。
4. 项目原则不设节点：在制定方案、一致性分析与实现的补充说明中要求读取并遵守目标仓库的 `.specify/memory/constitution.md`、`AGENTS.md`、`CONTRIBUTING.md` 等文件，违反“必须”条款判为严重。
5. 五份模板（`spec.md`、`plan.md`、`tasks.md`、`analysis.md`、`convergence.md`）按 ADR 0035 随流程保存在 `workflows/spec_kit/templates/`。结构沿用 spec-kit 并译为中文，删去建分支、运行脚本、扩展钩子等只适用于 spec-kit 命令行的步骤；`analysis.md` 与 `convergence.md` 取自 analyze、converge 命令规定的报告格式。每份模板的 front matter 写明上游路径与“MIT License，Copyright GitHub, Inc.”。
6. 活动右栏增加“补充说明”多行编辑框，对应节点字段 `instruction`。这份流程的方法约束主要写在补充说明里；内置流程只读显示，复制后可以修改。

## 取舍

- 没有把 spec-kit 的多份设计文件（research、data-model、contracts、quickstart）拆成独立产物，而是作为实现方案的章节，减少产物数量与模板维护量。
- 澄清没有新增“人填写答案”的交互，沿用决策点不通过时的附言；以后若决策点支持逐题作答，可以替换。
- `workflow-2` 保持不动，由人自行处理。
