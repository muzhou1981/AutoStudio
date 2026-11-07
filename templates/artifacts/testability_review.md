---
artifact: testability_review
producer: tester
consumers: [project_manager]
phase: draft
template_upstream: AutoStudio（无专用 GitHub 模板；列结构见 artifact-template-sources.md）
template_url: ""
---

# 可测试性评审（Testability Review）

**Date**: YYYY-MM-DD  
**针对**: requirement_spec（草稿）revision {{revision}}

## 1. 评审结论摘要

- 可进入需求确认关卡：是 | 否（待修订 AC）
- 阻塞项数量: {{n}}

## 2. 按验收标准评审

| AC-n | 问题类型 | 说明 | 改写建议 | 状态 |
|------|----------|------|----------|------|
| AC-1 | 不可判定 / 含糊 / 缺边界 / 无验证方式 | | | open / resolved |

**问题类型说明**:

- **不可判定**: 无法客观判断通过与否  
- **含糊**: 多种理解  
- **缺边界**: 未定义边界值或异常路径  
- **无验证方式**: 未说明测试、命令或可观察行为  

## 3. 建议新增的验收条目（如有）

| 建议 AC | 理由 |
|---------|------|
| | |

## 4. 开放问题

| # | 问题 | 建议澄清方 |
|---|------|------------|
| 1 | | 项目经理 / 人类 |
