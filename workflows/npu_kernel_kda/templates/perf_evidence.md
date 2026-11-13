---
artifact: perf_evidence
producer: architect
consumers: [developer, architect]
template_upstream: NVlabs/kda — docs/agent-flow.md 的证据记录与晋升规则（CC BY 4.0，Copyright NVIDIA CORPORATION & AFFILIATES）；mit-han-lab/ncu-report-skill 的六维诊断（MIT License，Copyright (c) 2026 hanlab）。已译为中文，并把 Nsight Compute 指标改为 nxperf 与 npcc++ 汇编可得的证据
template_url: https://github.com/mit-han-lab/ncu-report-skill
---

# 性能证据与候选台账：[算子名]

**日期**：YYYY-MM-DD
**台架与型号**：

<!--
  先剖析、再诊断、后计划，不凭猜测下结论。只有 SVB 板端数据可以作为接受依据；
  ESL 与静态分析只能说明方向。台账逐轮追加，已否决的候选不得删除。
-->

## 本轮测量

| 代表性形状 | 父候选耗时 | 本候选耗时 | 变化 | 离散程度 | 迭代次数 |
|------------|------------|------------|------|----------|----------|
| S1 | | | | | |

- **测量条件**：<!-- 同一会话、同一板卡、同一形状；nxperf 计时模式的命令 -->
- **加权结果**：<!-- 按合同中的形状权重汇总 -->

## 诊断

<!-- 每个维度写证据与结论；没有证据的维度写“未测”，不要推测。 -->

1. **启动几何与核利用**：grid 与 block 配置、各 Cluster 与各核是否都有任务、block 是否为 128 的倍数。
2. **负载均衡与尾部**：nxperf 逐核模式下各核耗时的差异，尾部 block 是否拖长总时间。
3. **指令与调度**：npcc++ 汇编中的指令构成、寄存器用量、标量与 SIMT 多发射是否被利用、32 位整数乘等宏指令开销。
4. **矩阵单元利用**（使用 Cayley 时）：MME 粒度是否对齐、Cayley 网格并行度是否用满、两路 block 任务是否并发。
5. **时间线**：nxperf 记录的 kernel 间隙、stream 并发、主机侧开销。
6. **访存**：是否合并访问、cacheline 对齐情况、Shared Memory 用量、实测带宽与目标型号上限之比（注明上限口径）。

## 本轮取舍

- **决定**：保留 / 修改 / 否决
- **理由**：
- **下一个候选**：<!-- 编号与要做的改动；没有值得尝试的候选时写明阻塞原因 -->

## 候选台账

| 编号 | 父候选 | 改动 | 正确性 | 加权变化 | 状态 | 理由 |
|------|--------|------|--------|----------|------|------|
| C0 | — | 基线 | 通过 | — | 基线 | |

## 晋升判断

<!-- 对照合同的晋升标准逐条判断；达到时结论为 pass，否则为 fail。 -->
