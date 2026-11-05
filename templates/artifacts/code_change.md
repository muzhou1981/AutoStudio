---
artifact: code_change
producer: developer
consumers: [code_reviewer, tester, qa]
template_upstream: pinecone-io/.github — pull_request_template.md
template_url: https://github.com/pinecone-io/.github/blob/main/.github/pull_request_template.md
---

# 代码变更说明（Code Change）

**Run**: {{run_id}}  
**Date**: YYYY-MM-DD  
**Attempt**: {{n}}

## Problem

（本变更要解决的问题；对应 TASK-n / AC-n。）

## Solution

（实现思路；链接 architecture_design / ui_spec 条目。）

## 范围对照

| TASK-n | 状态 | 说明 |
|--------|------|------|
| TASK-1 | done / partial | |

| AC-n | 覆盖方式 |
|------|----------|
| AC-1 | |

| SCR/CMP（若适用） | 实现位置 |
|-------------------|----------|
| SCR-1 | |

## 变更文件

| 路径 | 变更类型 |
|------|----------|
| | add / modify / delete |

## Type of Change

- [ ] Bug fix
- [ ] Feature
- [ ] Breaking change
- [ ] 仅测试 / 文档

## Test Plan（本地自证）

```bash
# 构建 / 测试命令
```

| 命令 | 结果 |
|------|------|
| | pass / fail |

## 已知限制

- 
