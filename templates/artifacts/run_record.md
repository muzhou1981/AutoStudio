---
artifact: run_record
producer: engine
consumers: [process_owner, config_manager]
template_upstream: auto_studio（本轮运行索引；可参考复盘 Data coverage 表）
template_url: ""
---

# 运行记录（Run Record）

> 引擎在 Run 结束或复盘前维护 **一份** 本轮索引；`retro_report`、`config_retro` 引用本记录，不重复粘贴全文产物。

**Run ID**: {{run_id}}  
**Thread ID**: {{thread_id}}  
**Started**: YYYY-MM-DDTHH:MM:SSZ  
**Ended**: YYYY-MM-DDTHH:MM:SSZ | In progress  
**scenario_key**: | **project_id**:

## 1. 输入摘要

| 字段 | 值 |
|------|-----|
| human_request | （摘要或 hash，非全文） |
| design_track_enabled | true / false |
| workflow.profile_id | |

## 2. 产物覆盖（Data coverage）

| Artifact | Version / revision | Producer node | Gate passed | Storage path |
|----------|-------------------|---------------|-------------|--------------|
| requirement_spec | v1 | project_manager_draft | gate_requirement_confirm | |
| config_plan | | config_manager_plan | | |
| … | | | | |

## 3. 关卡与决策

| Gate | Outcome | Human / time | baseline_log Entry |
|------|---------|--------------|-------------------|
| gate_requirement_confirm | approved | | BL-… |
| gate_architecture_review | | | |
| gate_final_delivery | | | |

## 4. 成本与质量指针

| 指针 | 引用 |
|------|------|
| cost_ledger | 末条 Entry ID 或文件路径 |
| cost_report | snapshot phase |
| review_status / test_status / qa_status | 最终 pass/fail |
| dev_retry_count | |
| change_request | CR-n 列表（若有） |

## 5. 对话与外部引用（可选）

| 类型 | ID / URL |
|------|----------|
| LangGraph thread | |
| 目标仓库 commit | |
