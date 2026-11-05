# 产物模板（artifacts）

各角色输出件与引擎级运行数据对应 **一份** Markdown 模板（`human_request` 仍为自由文本，无模板）；YAML 头部供 `config_plan` 引用。正文结构来自 GitHub 公开模板（见各文件 `template_upstream`），已按工厂字段（`AC-n`、`TASK-n` 等）裁剪。

| 文件 | 产物 | 产出角色 |
|------|------|----------|
| `requirement_spec.md` | 需求说明 | project_manager |
| `delivery_report.md` | 交付报告 | project_manager |
| `testability_review.md` | 可测试性评审 | tester |
| `test_cases.md` | 测试用例 | tester |
| `test_report.md` | 测试报告 | tester |
| `ux_spec.md` | 体验设计说明 | ux_designer |
| `ui_spec.md` | 界面规格 | ui_designer |
| `visual_assets.md` | 视觉资源清单 | visual_designer |
| `architecture_design.md` | 架构设计 | architect |
| `task_plan.md` | 任务计划 | architect |
| `code_change.md` | 代码变更说明 | developer |
| `change_request.md` | 变更请求 | 多角色 |
| `review_report.md` | 代码评审报告 | code_reviewer |
| `qa_report.md` | QA 报告 | qa |
| `budget_plan.md` | 预算方案 | finance |
| `cost_report.md` | 成本报告 | finance |
| `config_plan.md` | 配置管理计划 | config_manager |
| `baseline_log.md` | 基线登记（单条） | config_manager |
| `config_baseline.md` | 交付基线 | config_manager |
| `config_retro.md` | 模板与配置复盘 | config_manager |
| `config_proposals.md` | 配置改进提案 | config_manager |
| `retro_report.md` | 流程复盘 | process_owner |
| `process_proposals.md` | 流程改进提案 | process_owner |
| `cost_ledger.md` | 成本台账（追加日志） | engine |
| `run_record.md` | 运行记录（本轮索引） | engine |

上游 License 合入前请自行核对；完整调研见 [artifact-template-sources.md](../../docs/templates/artifact-template-sources.md)。
