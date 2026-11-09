---
artifact: config_plan
producer: config_manager
consumers: [all execution roles, architect, finance]
template_upstream: GeniStudio（无 GitHub 对标）
template_url: ""
---

# 配置管理计划（Config Plan）

**Run**: {{run_id}}  
**Date**: YYYY-MM-DD  
**scenario_key**: {{key}}  
**design_track_enabled**: true | false

## 1. 场景与仓库

| 项 | 值 |
|----|-----|
| 场景配置路径 | scenarios/… |
| 目标仓库 / 工作树 | |
| 分支命名 | |
| 工作树路径 | |

## 2. 产物 → 模板

| 产物 | 模板路径 | 存放规则 |
|------|----------|----------|
| requirement_spec | templates/artifacts/requirement_spec.md | … |
| task_plan | templates/artifacts/task_plan.md | |

## 3. 命名与版本

- 文件命名:
- 版本标识:

## 4. 基线点

| 关卡 | 纳入基线的产物 |
|------|----------------|
| gate_requirement_confirm | requirement_spec |
| gate_architecture_review | architecture_design, task_plan |
| gate_final_delivery | delivery_report, … |

## 5. 工具与 MCP（场景叠加）

| 角色 | 追加 skills/MCP |
|------|-----------------|
| developer | |
