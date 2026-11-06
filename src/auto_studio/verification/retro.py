"""用本轮状态里的证据写复盘打分。提案保持待批准，不修改角色或流程。"""

from __future__ import annotations

from typing import Any

from auto_studio.verification.acceptance import (
    extract_acceptance_ids,
    missing_acceptance_ids,
)


def _pad(items: list[str]) -> list[str]:
    filled = list(items[:3])
    while len(filled) < 3:
        filled.append("本轮没有更多该项证据。")
    return filled


def scorecard(state: dict[str, Any]) -> str:
    retries = int(state.get("dev_retry_count") or 0)
    qa = str(state.get("qa_status") or "unknown")
    baseline = str(state.get("baseline_log") or "")
    requirement = str(state.get("requirement_spec") or "")
    evidence = "\n".join(
        str(state.get(key) or "")
        for key in ("test_report", "qa_report", "testability_review")
    )
    ac_ids = extract_acceptance_ids(requirement)
    missing = missing_acceptance_ids(requirement_spec=requirement, evidence=evidence)
    cost_lines = [line for line in str(state.get("cost_ledger") or "").splitlines() if line.strip()]
    approved = "decision=approved" in baseline
    rejected = "decision=rejected" in baseline

    valuable: list[str] = []
    if ac_ids and not missing:
        valuable.append("验收编号均出现在测试或 QA 证据中。")
    if retries == 0:
        valuable.append("返工次数 dev_retry_count=0，本轮没有开发回退。")
    else:
        valuable.append(f"返工次数已记入证据：dev_retry_count={retries}。")
    if approved:
        valuable.append("关卡结论含批准，并写入基线。")
    if cost_lines:
        valuable.append(f"成本账本有 {len(cost_lines)} 行调用记录。")
    if qa == "pass":
        valuable.append("QA 结论为通过。")

    improve: list[str] = []
    if retries > 0:
        improve.append(f"返工 dev_retry_count={retries} 次，需对照 code_change 与 test_report。")
    if missing:
        improve.append("证据未覆盖验收编号：" + "、".join(missing) + "。")
    elif not ac_ids:
        improve.append("需求说明没有 AC-* 编号，交付不能逐条对照。")
    if not cost_lines:
        improve.append("成本账本为空，复盘不能引用调用次数。")
    if rejected:
        improve.append("基线中有驳回的关卡结论。")
    if qa not in {"pass", ""}:
        improve.append(f"QA 结论为 {qa}。")

    lines = [
        "## 复盘打分",
        (
            f"- 证据：返工次数 dev_retry_count={retries}；qa_status={qa}；"
            f"baseline_log={'有' if baseline.strip() else '无'}；成本行={len(cost_lines)}"
        ),
        "## Top3 有价值",
    ]
    lines.extend(f"{index}. {item}" for index, item in enumerate(_pad(valuable), start=1))
    lines.append("## Top3 待改进")
    lines.extend(f"{index}. {item}" for index, item in enumerate(_pad(improve), start=1))
    lines.append("提案状态：pending。未经批准不得修改角色定义或流程。")
    return "\n".join(lines)
