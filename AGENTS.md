# auto_studio · Agent 协作说明

本文件是在 Cursor 中开发 auto_studio 自身时的入口。

## 开始任务前

1. 阅读 [`docs/requirements.md`](docs/requirements.md)，了解原始需求、补充需求与已确认决策。
2. 涉及架构或技术选型时，阅读 [`docs/architecture.md`](docs/architecture.md) 与 [`docs/decisions/`](docs/decisions/)。
3. 涉及排期或里程碑时，阅读 [`docs/plans/roadmap.md`](docs/plans/roadmap.md)。

## 约束

- 本目录上下文自包含：新的需求、计划、决策写入 `docs/`，不依赖会话记忆。
- `roles/` 下的角色定义与 `src/auto_studio/workflows/default.py` 由人工编写；未经明确要求，Agent 不得创建或改写。
- 引用 `agents/skills` 下的技能时只按路径引用，不复制，也不让 `agents/skills` 反向依赖本目录。
- 重要技术决策新增一篇 `docs/decisions/NNNN-<slug>.md`。
- 改动 `src/` 后运行 `pytest` 与 `ruff check`。
