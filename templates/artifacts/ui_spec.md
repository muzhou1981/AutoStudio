---
artifact: ui_spec
producer: ui_designer
consumers: [visual_designer, developer, tester, code_reviewer]
template_upstream: jmagly/aiwg — wireframe-specification-template.md
template_url: https://github.com/jmagly/aiwg/blob/main/agentic/code/frameworks/sdlc-complete/templates/ux/wireframe-specification-template.md
---

# 界面规格（UI Spec）

**ID**: UI-{{project}}-001  
**Date**: YYYY-MM-DD  
**Status**: draft | approved  
**Related**: ux_spec（FLOW-n / WF-n）, task_plan（TASK-n）

## 1. 设计令牌（Design Tokens）

| Token | 值 | 用途 |
|-------|-----|------|
| color.primary | | |
| spacing.md | | |
| radius.sm | | |

## 2. 组件

### CMP-1: {{组件名}}

**用途**:  
**变体**: default | hover | disabled | loading | error  
**Maps to FLOW**: FLOW-1  
**Maps to TASK**: TASK-3

| 属性 | 规格 |
|------|------|
| 尺寸 / 间距 | |
| 文案 | |
| 图标 AST-n | |

## 3. 屏幕

### SCR-1: {{屏幕名}}

**Purpose**:  
**Entry / Exit**: 引用 ux_spec FLOW-1  
**Layout**: （结构描述或线框）

| 区域 | 组件 | 行为 |
|------|------|------|
| | CMP-1 | |

**状态**: 默认 | 加载 | 空 | 错误

## 4. 响应式 / 平台差异

| 断点 / 平台 | 差异 |
|-------------|------|
| | |

## 5. 资源占位

| 槽位 | AST-n / 文件名 | 状态 |
|------|----------------|------|
| 图标 | 待美工 | placeholder |

## 6. 与任务计划对照

| TASK-n | SCR/CMP | 完成判定 |
|--------|---------|----------|
| TASK-1 | SCR-1 | |
