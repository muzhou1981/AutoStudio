---
artifact: delivery_report
producer: project_manager
consumers: [human, config_manager]
phase: final
template_upstream: Aniekanetim/AI-Agent-Software-QA — release-signoff（交付包章节）
template_url: https://github.com/Aniekanetim/AI-Agent-Software-QA/blob/main/QA/Quality%20assurance/release-signoff.md
---

# 交付报告（Delivery Report）

**Run / 版本**: {{run_id}}  
**Date**: YYYY-MM-DD  
**Target build**: {{commit_or_tag}}  
**Audience**: 人类最终交付关卡

## 1. 身份与目的

| 字段 | 内容 |
|------|------|
| 本轮目标 | |
| 需求基线 | requirement_spec 版本 / revision |
| 测试与 QA 依据 | test_report、qa_report 引用 |

## 2. 发布说明（面向读者）

- 用户可见变更与影响
- 已知问题与限制
- 兼容性 / 配置 / 迁移说明

## 3. 验收标准逐条对照

| AC-n | 结论（满足/不满足/有条件） | 证据位置 |
|------|---------------------------|----------|
| AC-1 | | qa_report §… / test_report §… |

## 4. 验证摘要

- 测试执行结论（引用 `test_report`）
- QA 门禁结论（引用 `qa_report.verdict`）
- 未测区域与理由

## 5. 风险与遗留项

| 项 | 影响 | 负责人 | 是否阻塞交付 |
|----|------|--------|--------------|
| | | | |

## 6. 预算执行

| 项 | 内容 |
|----|------|
| 批准预算 | 引用 budget_plan（正式版） |
| 实际成本 | 引用 cost_report（snapshot） |
| 偏差说明 | |

## 7. 交付建议

- **建议**: 批准交付 | 有条件批准 | 不批准  
- **理由**（每条结论指向证据）:

## 8. 运维/接收交接（如适用）

- 接收方、下一步动作、复现链接、回滚说明
