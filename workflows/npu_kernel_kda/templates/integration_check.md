---
artifact: integration_report
producer: tester
consumers: [developer, architect]
template_upstream: 本流程自有模板
template_url: ''
---

# 集成核对报告：[算子名]

**核对对象**：integration_change
**日期**：YYYY-MM-DD
**台架**：

## 核对项

| 核对项 | 方法 | 结果 | 证据位置 |
|--------|------|------|----------|
| 代表用例编译通过 | | 通过 / 失败 / 不适用 | |
| 用例走到新实现 | | | |
| graph_cut 生效 | | | |
| manual_config 生效 | | | |
| 约束检查对不支持的输入回退 | | | |
| 板端正确性回归 | | | |

<!-- 接入说明写明无需接入的，只核对理由是否成立，其余项写“不适用”。 -->

## 问题与复现

<!-- 没有问题时写“无”。 -->

## 结论

<!-- 任何一项不满足时为 fail。 -->
