---
artifact: cost_report
producer: finance
consumers: [project_manager, process_owner]
phase: snapshot
template_upstream: auto_studio（无 GitHub 对标；phase: snapshot | final）
template_url: ""
---

# 成本报告（Cost Report）

**Phase**: snapshot | final  
**Date**: YYYY-MM-DD  
**cost_ledger 截止**: {{timestamp}}

## 1. 预算对比

| 项 | 预算（budget_plan） | 实际 | 偏差 |
|----|---------------------|------|------|
| 合计 | | | |

## 2. 按角色

| 角色 | 实际 | 占比 |
|------|------|------|
| | | |

## 3. 按节点 / 后端 / 模型

| 节点 | 后端 | 模型 | 用量 | 金额 |
|------|------|------|------|------|
| developer | | | | |

## 4. 返工与重试

| 原因 | 额外成本 |
|------|----------|
| review fail 回退 | |

## 5. 偏差分析

- 

## 6. 追溯

每条金额须可指向 `cost_ledger` 记录 id:

| ledger_id | 金额 | 说明 |
|-----------|------|------|
| | | |
