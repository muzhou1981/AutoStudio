---
artifact: change_request
producer: developer
consumers: [project_manager, architect, config_manager]
template_upstream: appwrite/rfc — rfc-template.md（Problem/Summary 结构 + 工厂字段）
template_url: https://github.com/appwrite/rfc/blob/main/rfc-template.md
---

# 变更请求（Change Request）

**ID**: CR-{{run_id}}-{{seq}}  
**raised_by**: developer | tester | …  
**Date**: YYYY-MM-DD  
**Status**: open | accepted | rejected | deferred

## Summary

（一句话：要改什么、为什么。）

## Target

| 字段 | 值 |
|------|-----|
| target_artifact | requirement_spec | architecture_design | task_plan | ui_spec | … |
| 当前版本 / revision | |

## Problem Statement

（问题背景；**不要**在此写完整替代方案正文。）

## Impacted acceptance criteria

| AC-n | 影响 |
|------|------|
| AC-1 | 范围 / 判定 / 新增 |

## Recommended owner

- project_manager（验收/范围）  
- architect（设计/任务）  
- ux_designer / ui_designer（体验/界面）

## Disposition

| 字段 | 值 |
|------|-----|
| 评估人 | |
| 决定 | 采纳 / 拒绝 / 需人类关卡 |
| 需重新过关卡 | gate_requirement_confirm | gate_architecture_review | — |

## 批准与登记

- config_manager baseline_log 条目: BL-…（批准后填写）
