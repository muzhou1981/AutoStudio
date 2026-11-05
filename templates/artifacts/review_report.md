---
artifact: review_report
producer: code_reviewer
consumers: [developer, qa]
template_upstream: awesome-skills/code-review-skill — review-checklist.md
template_url: https://github.com/awesome-skills/code-review-skill/blob/main/assets/review-checklist.md
---

# 代码评审报告（Review Report）

**Round**: 1  
**Date**: YYYY-MM-DD  
**code_change attempt**: {{n}}

## 总体结论

- **Verdict**: 通过 | 需修改  
- **对照**: architecture_design, task_plan, ui_spec（界面任务）

## 意见列表

| RV-n | 级别 | 文件:位置 | 问题 | 建议 | 状态 |
|------|------|-----------|------|------|------|
| RV-1 | 阻断 / 建议 / 细节 | path:42 | | | open / closed |

级别与 checklist 对应：阻断 = `[blocking]`，必须修复后合入。

## 设计 / 计划一致性

| 项 | 结论 |
|----|------|
| 是否只做 task_plan 范围 | |
| 与 AD-n 一致 | |

## 测试充分性

- [ ] 新行为有测试
- [ ] 关键路径与边界
- [ ] 无删/跳过/弱化测试

## 快速检查摘要（可选）

- 逻辑与正确性: ok / issues
- 安全: ok / issues
- 性能: ok / issues

## 复审记录（Round > 1）

| RV-n | 上轮状态 | 本轮 |
|------|----------|------|
| RV-1 | open | closed |
