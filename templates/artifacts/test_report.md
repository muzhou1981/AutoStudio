---
artifact: test_report
producer: tester
consumers: [developer, qa, project_manager]
template_upstream: fugazi/test-automation-skills-agents — test-summary-report.md
template_url: https://github.com/fugazi/test-automation-skills-agents/blob/main/skills/qa-manual-istqb/templates/test-summary-report.md
---

# 测试报告（Test Report）

## 1. 文档控制

- **Project / Run**: {{run_id}}
- **Release / Iteration**: 
- **Date**: YYYY-MM-DD
- **Owner**: 测试工程师

## 2. 范围与目标

- 测试范围（在测）
- 不在范围及原因
- 针对的质量风险

## 3. 环境与命令

| 项 | 内容 |
|----|------|
| 环境 | |
| 分支 / commit | |
| 执行命令 | `…` |

## 4. 活动与结果

| 指标 | 数量 |
|------|------|
| 执行 | |
| 通过 | |
| 失败 | |
| 跳过 | |

### 4.1 用例结果

| TC-n | AC-n | 结果 | 备注 |
|------|------|------|------|
| TC-001 | AC-1 | PASS / FAIL / SKIP | |

### 4.2 缺陷（DEF-n）

#### DEF-001: {{标题}}

- **关联**: TC-001, AC-1
- **复现步骤**: 
- **实际 / 期望**: 
- **日志 / 附件**: 

## 5. 验收标准覆盖

| AC-n | 覆盖 TC | 结论 |
|------|---------|------|
| AC-1 | TC-001, TC-002 | pass / fail |

## 6. 残余风险与建议

- 未覆盖区域
- 建议回归范围

## 7. 出口结论

- **Exit criteria**: met | not met
- **建议**: 进入 QA | 退回开发
