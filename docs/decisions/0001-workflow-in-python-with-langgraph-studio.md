# 0001 · 流程以 Python 编写，并用 LangGraph Studio 调试

- 状态：已接受
- 日期：2026-11-05

## 背景

工作流程通过 LangGraph 编排。可选方式有三种：直接以 Python 编写图；先写声明式 YAML 再编译成图；图结构用 Python、节点参数放 YAML。

## 决策

第一版直接以 Python 编写 LangGraph 图，放在 `src/geni_studio/workflows/`。在根目录 `langgraph.json` 中注册图，通过 `langgraph dev` 启动本地服务，用 LangGraph Studio 可视化与调试。

## 理由

- LangGraph 以代码定义图为主；额外的 YAML 层需要自行实现解析与校验，而当前只有一套流程。
- LangGraph Studio 只做可视化与调试，不做拖拽编辑，图结构仍以代码为准，与本决策一致。

## 影响

- 出现多套流程，或进化需要频繁调整流程结构时，再评估提炼声明式格式。
- Studio 只能看到图层面的节点与状态。节点内后端 Agent 的工具调用，须由后端插件写回图状态摘要；完整对话记录存放在 `runs/<run_id>/transcripts/`。
- 使用 Studio 需要 LangSmith 账号与 API key；`.env` 中设置 `LANGSMITH_TRACING=false` 使运行数据只留在本地。
