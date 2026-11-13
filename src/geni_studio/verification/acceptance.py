"""验收标准提取与逐条对照。

一个验收编号视为通过，须满足其一：判定类活动的结论块中该编号为 pass；
或验证命令退出码为 0 且其输出含该编号。仅在正文中出现不算覆盖。
Stub 后端的模拟运行没有真实证据，退回到“出现即覆盖”，并在对照表中注明。
"""

from __future__ import annotations

import re

from geni_studio.verification.verdict import Verdict, accepted_ids

_AC = re.compile(r"\b(AC-\d+)\b")
_IMPACT = re.compile(r"IMPACT:\s*(scope|architecture)\b", re.IGNORECASE)
_COMMAND = re.compile(r"## 测试命令\n```\n(?P<body>.*?)\n```", re.DOTALL)


def extract_acceptance_ids(text: str) -> list[str]:
    found: list[str] = []
    for match in _AC.finditer(text or ""):
        ac = match.group(1)
        if ac not in found:
            found.append(ac)
    return found


def missing_acceptance_ids(*, requirement_spec: str, evidence: str) -> list[str]:
    """按“出现即覆盖”计算缺口；仅用于模拟运行与复盘统计。"""
    seen = set(extract_acceptance_ids(evidence))
    return [ac for ac in extract_acceptance_ids(requirement_spec) if ac not in seen]


def machine_accepted_ids(report: str) -> set[str]:
    """测试报告中退出码为 0 的验证命令输出所含的验收编号。"""
    found: set[str] = set()
    for match in _COMMAND.finditer(report or ""):
        body = match.group("body")
        if re.search(r"(?m)^exit=0$", body):
            found.update(extract_acceptance_ids(body))
    return found


def acceptance_sources(
    *,
    requirement_spec: str,
    verdicts: list[Verdict | None],
    test_report: str,
    simulated_evidence: str | None = None,
) -> dict[str, str]:
    """每个验收编号的证据来源；空串表示缺少证据。"""
    by_verdict: set[str] = set()
    for verdict in verdicts:
        by_verdict |= accepted_ids(verdict)
    by_command = machine_accepted_ids(test_report)
    mentioned = set(extract_acceptance_ids(simulated_evidence)) if simulated_evidence is not None else set()
    out: dict[str, str] = {}
    for ac in extract_acceptance_ids(requirement_spec):
        if ac in by_command:
            out[ac] = "验证命令输出"
        elif ac in by_verdict:
            out[ac] = "结论块"
        elif ac in mentioned:
            out[ac] = "模拟运行（无真实证据）"
        else:
            out[ac] = ""
    return out


def acceptance_matrix(sources: dict[str, str]) -> str:
    if not sources:
        return (
            "## 验收对照\n"
            "需求说明中没有 AC-* 编号。交付关卡不能把该说明当作已逐条验证的证据。"
        )
    lines = ["## 验收对照"]
    for ac, source in sources.items():
        lines.append(f"- {ac}: {source or '缺失'}")
    if any(not source for source in sources.values()):
        lines.append("结论：证据未覆盖全部验收标准，不能视为交付。")
    else:
        lines.append("结论：所列验收标准均有证据。")
    return "\n".join(lines)


def classify_change_impact(change_request: str) -> str:
    from geni_studio.verification.verdict import parse_change_request

    impact, _ = parse_change_request(change_request or "")
    if impact:
        return impact
    match = _IMPACT.search(change_request or "")
    if not match:
        return ""
    return match.group(1).lower()
