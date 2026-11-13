---
artifact: integration_change
producer: developer
consumers: [tester, architect]
template_upstream: 本流程自有模板；对应 NVlabs/kda 中把 kernel 导出到交付形态的环节，交付对象改为 OPLIB/AOM
template_url: https://github.com/NVlabs/kda/blob/main/docs/huggingface-export.md
---

# 接入说明：[算子名]

**日期**：YYYY-MM-DD
**编程路线**：CCA / Hauk / AOM 图级接入

## 是否需要接入

<!-- 需要接入时写“是”；不需要时写明理由（例如只替换已登记算子的内部实现），以下各节写“不适用”。 -->

## 改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| | | |

## 登记与约束检查

- **算子登记**：<!-- 登记位置；确认同一算子没有重复登记 -->
- **约束检查**：<!-- 补齐的形状、数据类型、对齐等检查，不满足时的回退路径 -->

## 配置

- **manual_config**：<!-- 所属 lib_op_type 与调优项 -->
- **graph_cut**：<!-- 键必须是编译后的 Call 名，不能用注册表中的算子名 -->
- **graph_option**：<!-- enable_dyn_cut、enable_op_cut 是否调整及原因 -->

## 自测

<!-- 本地编译与最小用例结果。 -->
