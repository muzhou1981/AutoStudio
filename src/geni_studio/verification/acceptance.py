"""验收标准提取与逐条对照。"""

from __future__ import annotations

import re

_AC = re.compile(r"\b(AC-\d+)\b")
_IMPACT = re.compile(r"IMPACT:\s*(scope|architecture)\b", re.IGNORECASE)


def extract_acceptance_ids(text: str) -> list[str]:
    found: list[str] = []
    for match in _AC.finditer(text or ""):
        ac = match.group(1)
        if ac not in found:
            found.append(ac)
    return found


def missing_acceptance_ids(*, requirement_spec: str, evidence: str) -> list[str]:
    seen = set(extract_acceptance_ids(evidence))
    return [ac for ac in extract_acceptance_ids(requirement_spec) if ac not in seen]


def acceptance_matrix(*, requirement_spec: str, evidence: str) -> str:
    ids = extract_acceptance_ids(requirement_spec)
    if not ids:
        return (
            "## 验收对照\n"
            "需求说明中没有 AC-* 编号。交付关卡不能把该说明当作已逐条验证的证据。"
        )
    missing = missing_acceptance_ids(requirement_spec=requirement_spec, evidence=evidence)
    lines = ["## 验收对照"]
    for ac in ids:
        mark = "缺失" if ac in missing else "已出现在测试或 QA 证据中"
        lines.append(f"- {ac}: {mark}")
    if missing:
        lines.append("结论：证据未覆盖全部验收标准，不能视为交付。")
    else:
        lines.append("结论：所列验收标准均在证据中出现。")
    return "\n".join(lines)


def classify_change_impact(change_request: str) -> str:
    match = _IMPACT.search(change_request or "")
    if not match:
        return ""
    return match.group(1).lower()
