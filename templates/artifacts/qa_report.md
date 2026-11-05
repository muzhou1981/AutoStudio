---
artifact: qa_report
producer: qa
consumers: [project_manager, developer]
template_upstream: ITSalt/NaCl — qa-report-template.md
template_url: https://github.com/ITSalt/NaCl/blob/main/nacl-tl-core/templates/qa-report-template.md
---

# QA 报告（QA Report）

---
test_date: YYYY-MM-DD
environment: dev | staging
verdict: PASS | FAIL
---

## 1. 范围

| 字段 | 值 |
|------|-----|
| requirement_spec revision | |
| 测试依据 | test_report, test_cases |

## 2. 验收标准逐条

| AC-n | Criterion 摘要 | Status | Evidence |
|------|----------------|--------|----------|
| AC-1 | | PASS / FAIL / N/A | 复测命令 / test_report TC-001 |

### N/A 说明

| AC-n | 原因 |
|------|------|
| | 非 UI 可测，见单元测试 |

### 汇总

| | Count |
|---|-------|
| Total | |
| Passed | |
| Failed | |
| N/A | |

## 3. 独立复核

| AC-n | 复核命令 / 步骤 | 结果 |
|------|-----------------|------|
| AC-1 | | |

## 4. 流程审计

| 检查项 | 结论 | 证据 |
|--------|------|------|
| 人工关卡已批准 | | baseline_log |
| 评审阻断已关闭 | | review_report |
| 基线变更有 change_request | | baseline_log |

## 5. 总体结论

- **Verdict**: PASS | FAIL  
- **退回对象**（若 FAIL）: developer | project_manager | …  
- **理由**:
