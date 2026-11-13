# 0037 · 内置 NPU 算子开发流程（KDA）

- 状态：已采纳
- 日期：2026-11-13

## 背景

[NVlabs/kda](https://github.com/NVlabs/kda)（Kernel Design Agents）给出一套与硬件无关的 kernel 开发方法：先写任务合同，读工作区后写方案草案，草案完成前不改代码；每次只实现一个候选，每次改动后验证，测量后把候选及其父子关系、测量与剖析证据记入台账，再决定保留、修改或否决；只有满足合同且有证据表明指标改善或不退化时才晋升。它的两个子模块分别提供 Nsight Compute 剖析与报告方法（`ncu-report-skill`，六维诊断）和 Blackwell/Hopper 优化知识（`KernelWiki`）。

现有内置流程 `npu_operator_dev` 及其 CCA、AOM 子图侧重实现闭包与分层验证，没有方案草案、候选台账与板端 A/B 取舍。KDA 的领域知识面向 NVIDIA GPU，不能直接套用到本公司 NX9031 NPU。

## 平台差异

依据 geni-wiki 图谱检索与本地技能 `cca-programming`、`cca-perf-tuning`、`use-nxperf`、`esl-benchmark`：

| 方面 | NX9031 NPU | NVIDIA（KDA 的目标为 B200） | 流程中的处理 |
|---|---|---|---|
| 计算核 | Fermat（SIMT，CCA 或 Hauk）与 Cayley（矩阵，仅 Hauk，无分支与执行掩码） | 统一的 SM，内含 Tensor Core | 合同锁定目标核与编程路线 |
| 型号 | N93X（V20，32 个 Fermat 核、16 个 Cayley 核）与 N93P（V21，20 个 Fermat 核、8 个 Cayley 核），可用指令与优化不同 | 单一目标卡 | 合同锁定目标型号，带宽上限不跨型号套用 |
| 执行与片上资源 | 硬件 Warp 128 线程；Shared Memory 每核 32KB；VGPR 每线程最多 224；L1 与 L2 cacheline 为 128B、256B | Warp 32 线程；Shared Memory 最大 228KB | 方案草案逐条核对平台资源门槛 |
| 带宽 | N93P float4 有效带宽约 142 GB/s，N93X 实测峰值约 346 GB/s | HBM3e，每秒数 TB | 静态诊断按目标型号的上限并注明口径 |
| 剖析 | nxperf（计时与逐核）、ESL 仿真、npcc++ 汇编，无 ncu | Nsight Compute | 六维诊断改写为可得证据；只有 SVB 板端数据可作接受依据 |
| 交付 | 接入 OPLIB/AOM，`graph_cut` 键为编译后的 Call 名 | 导出为 Hugging Face kernel | 增设接入算子库与集成核对 |

## 决定

1. 新增独立内置流程 `workflows/npu_kernel_kda/`，标题“NPU 算子开发（KDA）”，`builtin: true`；`profile` 与 `npu_operator_dev` 相同（关闭设计轨道）。现有 `npu_operator_dev` 及其子图、`llm_fullnet` 保持不动。
2. 节点：

   | 节点 | 角色 | 对应 |
   |---|---|---|
   | 算子合同 | 架构师 | 任务合同，补充型号、目标核、路线、代表性形状、分层验证与 nxperf 评测命令 |
   | 确认合同 | 人 | 4 个决策项，不通过回到算子合同 |
   | 方案草案 | 架构师 | draft：静态诊断、平台资源门槛、候选排序；要求检索 geni-wiki |
   | 审方案 | 人 | 3 个决策项，不通过回到方案草案 |
   | 实现候选 | 程序员 | 每轮一个候选、一项改动 |
   | 分层验证 | 测试工程师 | 静态检查、独立编译、runtime、libop.so、SVB；不通过回到实现候选，最多 3 次 |
   | 诊断与取舍 | 架构师 | 板端 nxperf A/B、六维诊断、候选台账；未达晋升标准回到实现候选，最多 4 次 |
   | 接入算子库 | 程序员 | OPLIB/AOM 登记、manual_config、graph_cut；无需接入时写明理由 |
   | 集成核对 | 测试工程师 | 不通过回到接入算子库，最多 2 次 |
   | 算子报告 | 架构师 | 改编自 ncu-report-skill 的报告模板 |
   | 晋升评审 | 人 | 4 个决策项，不通过回到实现候选 |

3. 接受优化必须有 SVB 板端 A/B 数据；ESL 仅在合同写明已获授权时运行，只作方向性参考。
4. 七份模板按 ADR 0035 随流程保存。取自 KDA 文档的合同、草案、验证报告与证据记录注明“CC BY 4.0，Copyright NVIDIA CORPORATION & AFFILIATES”及改编说明；取自 ncu-report-skill 的六维诊断与报告结构注明“MIT License，Copyright (c) 2026 hanlab”。接入说明与集成核对为本流程自有模板。
5. 复制流程时一并复制 `profile`。此前复制会丢弃该字段，而编辑器保存时会保留，导致内置 NPU 流程的副本重新打开设计轨道。

## 取舍

- 没有把 KernelWiki 的内容带入模板：其中的 tcgen05、TMEM、CuTe DSL 等知识只适用于 NVIDIA；本平台的对应知识以 geni-wiki 为准，在补充说明中要求检索。
- 性能循环与验证循环都回到实现候选，不回到方案草案：候选方向在草案中已排序，改方向的决定由性能诊断写进“下一个候选”；需要重写草案时由人在晋升评审或回退上限后处理。
- geni-wiki 未收录 Fermat、Cayley 的峰值算力，Roofline 的计算上限由同型号实测或 `cca-perf-tuning` 的参考值给出，待知识库补充后再收紧模板要求。
