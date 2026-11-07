---
artifact: cost_ledger
producer: engine
consumers: [finance]
template_upstream: AutoStudio（追加式用量/成本日志；无 GitHub 对标）
template_url: ""
---

# 成本台账（Cost Ledger）

> 引擎按 **节点/角色调用** 追加记录；财务只读，不手工改历史行。`cost_report` 中每项金额须能指向本台账 **Entry ID**。

**Run ID**: {{run_id}}  
**Ledger file / store**: （由 `config_plan.storage` 规定）

## 记录格式（每条一行或一行一表）

| Entry ID | Timestamp (UTC) | Node | Role | Backend | Model | Input tokens | Output tokens | Unit price | Amount | Currency | budget_phase | Note |
|----------|-----------------|------|------|---------|-------|--------------|---------------|------------|--------|----------|--------------|------|
| CL-001 | YYYY-MM-DDTHH:MM:SSZ | developer | developer | cursor | … | | | | | CNY | rough | |

## 汇总（可选，由引擎或 finance 刷新）

| budget_phase | 累计 Amount | 条数 |
|--------------|-------------|------|
| rough | | |
| final | | |
| snapshot | | |

## 规则

1. Entry ID 全局唯一（建议 `CL-{run_id}-{seq}`）。
2. 同一节点多次重试（如 `dev_retry_count`）各记一条，Note 中写 `attempt=n`。
3. 非 LLM 成本（人工关卡等待、外部 API）用 Node=`gate_*` 或 `human`，Model=`—`。
