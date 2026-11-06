"""用本轮状态里的证据写复盘打分。提案保持待批准，不修改角色或流程。"""

from __future__ import annotations

from typing import Any


def scorecard(state: dict[str, Any]) -> str:
    retries = int(state.get("dev_retry_count") or 0)
    qa = state.get("qa_status") or "unknown"
    baseline = "有" if (state.get("baseline_log") or "").strip() else "无"
    return "\n".join(
        [
            "## 复盘打分",
            f"- 证据：返工次数 dev_retry_count={retries}；qa_status={qa}；baseline_log={baseline}",
            "## Top3 有价值",
            "1. 人工关卡写入 baseline_log，批准依据可追溯。" if baseline == "有" else "1. （本轮没有基线记录，此项无证据）",
            "2. 验收标准以 AC-* 编号进入测试与 QA 对照。",
            "3. 回退超过上限后升级给人，而不是无限重试。",
            "## Top3 待改进",
            "1. 若 dev_retry_count 大于 0，说明实现或测试曾经失败，需看 code_change 与 test_report。",
            "2. 成本账本仍可能为空，复盘不能引用金额。",
            "3. 改进提案尚未经人批准，不能改角色定义或流程。",
            "提案状态：pending",
        ]
    )
