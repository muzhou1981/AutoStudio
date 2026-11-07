---
artifact: baseline_log
producer: config_manager
consumers: [qa, project_manager]
template_upstream: AutoStudio（追加式单条登记；无 GitHub 对标）
template_url: ""
---

# 基线登记（Baseline Log Entry）

> 每次关卡批准或基线变更追加 **一条**；勿覆盖历史条目。

**Entry ID**: BL-{{run_id}}-{{seq}}  
**Date**: YYYY-MM-DDTHH:MM:SSZ

## 登记类型

- [ ] 关卡批准（gate）
- [ ] 基线变更（change）

## 内容

| 字段 | 值 |
|------|-----|
| 关卡名称 | gate_requirement_confirm | … |
| 批准人 | human / {{id}} |
| 批准依据 | 关卡 thread / 链接 |
| 纳入基线产物 | name @ version |
| 关联 change_request | CR-n 或 — |

## 变更说明（仅 change 类型）

| 字段 | 值 |
|------|-----|
| 修改产物 | |
| change_request | |
| 重新过关卡 | yes / no |

## 配置管理员确认

- 与 config_plan 一致: yes | no  
- 备注:
