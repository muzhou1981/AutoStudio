"""决策点的逐项审批：把逐项结论汇总成整体结论与附言，见 ADR 0032。"""

from __future__ import annotations

from typing import Any


class ItemsError(ValueError):
    """逐项结论不完整或不合法。"""


def judge_items(
    checklist: dict[str, Any],
    given: list[dict[str, Any]] | None,
    decision: str | None,
) -> tuple[str | None, list[dict[str, str]]]:
    """返回整体结论与按定义顺序排列的逐项结论。

    未给逐项结论而整体批准时视为全部通过；「全部通过才放行」规则下整体结论由逐项结论得出。
    """
    items = checklist["items"]
    rule = checklist["pass_rule"]
    titles = {item["id"]: item["title"] for item in items}
    answers: dict[str, dict[str, str]] = {}
    for raw in given or []:
        item_id = str(raw.get("id") or "")
        if item_id not in titles:
            raise ItemsError(f"决策项「{item_id}」不在这个决策点上。")
        verdict = str(raw.get("decision") or "")
        if verdict not in ("approved", "rejected"):
            raise ItemsError(f"「{titles[item_id]}」要选通过或不通过。")
        note = str(raw.get("note") or "").strip()
        if verdict == "rejected" and not note:
            raise ItemsError(f"「{titles[item_id]}」不通过，要写明原因。")
        answers[item_id] = {"decision": verdict, "note": note}
    if not answers:
        if decision == "approved":
            answers = {item["id"]: {"decision": "approved", "note": ""} for item in items}
        elif rule == "all":
            raise ItemsError("这个决策点要逐项给出结论，请在网页逐项处理。")
    judged = [
        {"id": item["id"], "title": item["title"], **answers[item["id"]]}
        for item in items
        if item["id"] in answers
    ]
    if rule == "manual":
        return decision, judged
    missing = [item["title"] for item in items if item["required"] and item["id"] not in answers]
    if missing:
        raise ItemsError(f"还有 {len(missing)} 个必答项没有结论：" + "、".join(f"「{t}」" for t in missing) + "。")
    rejected = any(item["decision"] == "rejected" for item in judged)
    return ("rejected" if rejected else "approved"), judged


def items_section(judged: list[dict[str, str]]) -> str:
    if not judged:
        return ""
    lines = ["逐项结论："]
    for item in judged:
        if item["decision"] == "rejected":
            lines.append(f"- 不通过「{item['title']}」：{item['note']}")
        else:
            lines.append(f"- 通过「{item['title']}」" + (f"：{item['note']}" if item["note"] else ""))
    return "\n".join(lines)
