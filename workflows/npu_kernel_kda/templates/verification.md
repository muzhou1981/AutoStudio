---
artifact: verification_report
producer: tester
consumers: [developer, architect]
template_upstream: NVlabs/kda — docs/agent-flow.md 的“每次有意义的改动后验证”（CC BY 4.0，Copyright NVIDIA CORPORATION & AFFILIATES），已译为中文并按 NX9031 NPU 的分层验证改编
template_url: https://github.com/NVlabs/kda/blob/main/docs/agent-flow.md
---

# 分层验证报告：[算子名] 候选 [编号]

**被验证的改动**：code_change
**日期**：YYYY-MM-DD
**台架**：

<!--
  低层没过不跑高层。产物目录生成不等于板卡已跑通。
  ESL 仿真只有在合同写明已获授权时才运行，结果只作参考，不能代替板端。
-->

## 分层结果

| 层级 | 命令 | 结果 | 日志位置 |
|------|------|------|----------|
| 静态检查 | | 通过 / 失败 / 未运行 | |
| 独立编译（npcc++） | | | |
| runtime | | | |
| libop.so | | | |
| ESL 仿真（如已授权） | | | |
| SVB 板端 | | | |

## 正确性

| 代表性形状 | 最大绝对误差 | 最大相对误差 | 容差 | 结果 |
|------------|--------------|--------------|------|------|
| S1 | | | | |

## 资源用量

- **寄存器**：
- **Shared Memory**：
- **启动配置**：

## 失败与复现

<!-- 失败时写明层级、现象、复现命令与日志位置；全部通过时写“无”。 -->

## 结论

<!-- 任何一层失败或任何形状超出容差时为 fail。 -->
