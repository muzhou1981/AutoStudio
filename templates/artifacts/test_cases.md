---
artifact: test_cases
producer: tester
consumers: [tester, qa, developer]
template_upstream: jmagly/aiwg — test-documenter TC 规格
template_url: https://github.com/jmagly/aiwg/blob/main/plugins/sdlc/agents/test-documenter.md
---

# 测试用例（Test Cases）

**Feature / Run**: {{name}}  
**Date**: YYYY-MM-DD  
**Requirement baseline**: requirement_spec revision {{rev}}

## 追溯矩阵

| TC-n | 覆盖 AC-n | 设计参考（AD-n / FLOW-n，可选） | 优先级 |
|------|-----------|----------------------------------|--------|
| TC-001 | AC-1 | | P0 |

---

## TC-001: {{标题}}

**覆盖 AC**: AC-1, …  
**类型**: 功能 | 集成 | E2E | 回归  
**自动化**: 是 | 否

### 前置条件

- 

### 步骤与期望

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | | |
| 2 | | |

### 测试数据

```json
{}
```

### 边界与异常（可选）

- 

---

## TC-002: {{标题}}

（复制上一节结构。）
