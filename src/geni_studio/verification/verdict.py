"""评审、测试、QA 等判定类活动的结构化结论（verdict 围栏块）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pass", "fail"]

_BLOCK = re.compile(r"```[ \t]*(?P<tag>[A-Za-z_][\w-]*)[^\n]*\n(?P<body>.*?)\n?```", re.DOTALL)
_HEADING = re.compile(r"(?m)^#{1,6}[ \t]+`?(?P<name>[A-Za-z_]\w*)`?[ \t]*$")
_LEGACY_FAIL = re.compile(r"(?m)^STATUS:\s*fail\s*$")
_AC_STATES = {"pass", "fail", "untested"}
_IMPACTS = {"", "none", "scope", "architecture"}

VERDICT_INSTRUCTION = (
    "正文结束后，必须附上一个结构化结论块（围栏语言写 verdict，内容为 JSON）：\n"
    "```verdict\n"
    '{"status": "pass 或 fail", "ac": {"AC-1": "pass / fail / untested"}, '
    '"summary": "一句话结论"}\n'
    "```\n"
    "只有结论块决定是否通过；正文中提到验收编号不代表已验证。"
)

CHANGE_REQUEST_INSTRUCTION = (
    "若发现计划不可行、需要调整需求范围或架构，不要自行改变设计；在正文末尾附上：\n"
    "```change_request\n"
    '{"impact": "scope 或 architecture", "reason": "原因与建议"}\n'
    "```\n"
    "没有变更请求时不要写这个块。"
)


@dataclass(frozen=True)
class Verdict:
    status: Status
    ac: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    source: Literal["block", "legacy", "preset", "missing", "invalid"] = "block"
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def fenced_blocks(text: str, tag: str) -> list[str]:
    return [m.group("body") for m in _BLOCK.finditer(text or "") if m.group("tag") == tag]


def parse_verdict(text: str) -> Verdict | None:
    """取最后一个 verdict 块；没有返回 None，格式错误返回 invalid 的失败结论。"""
    blocks = fenced_blocks(text, "verdict")
    if not blocks:
        return None
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        return Verdict("fail", source="invalid", error=f"结论块不是合法 JSON：{exc.msg}")
    if not isinstance(data, dict):
        return Verdict("fail", source="invalid", error="结论块必须是 JSON 对象")
    status = str(data.get("status") or "").strip().lower()
    if status not in {"pass", "fail"}:
        return Verdict("fail", source="invalid", error="结论块的 status 只能是 pass 或 fail")
    raw_ac = data.get("ac") or {}
    if not isinstance(raw_ac, dict):
        return Verdict("fail", source="invalid", error="结论块的 ac 必须是对象")
    ac = {}
    for key, value in raw_ac.items():
        state = str(value or "").strip().lower()
        ac[str(key).strip()] = state if state in _AC_STATES else "untested"
    return Verdict(status, ac=ac, summary=str(data.get("summary") or "").strip())  # type: ignore[arg-type]


def judge(text: str, *, simulated: bool, preset: str = "pass") -> Verdict:
    """判定活动是否通过。

    真实后端缺少结论块时按失败处理；Stub 后端沿用预设结论，便于调试分支。
    """
    parsed = parse_verdict(text)
    if parsed is not None:
        return parsed
    if _LEGACY_FAIL.search(text or ""):
        return Verdict("fail", source="legacy")
    if simulated:
        return Verdict("fail" if preset == "fail" else "pass", source="preset")
    return Verdict("fail", source="missing", error="输出缺少结构化结论块（verdict），按未通过处理。")


def verdict_block(verdict: Verdict) -> str:
    payload = {"status": verdict.status, "ac": verdict.ac, "summary": verdict.summary}
    return "```verdict\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def with_verdict(body: str, verdict: Verdict) -> str:
    """去掉正文中旧的结论块，附上最终结论；判定失败原因写在结论块之前。"""
    cleaned = _BLOCK.sub(lambda m: "" if m.group("tag") == "verdict" else m.group(0), body or "").rstrip()
    note = f"\n\n> {verdict.error}" if verdict.error else ""
    return f"{cleaned}{note}\n\n{verdict_block(verdict)}"


def parse_change_request(text: str) -> tuple[str, str]:
    """返回（影响范围, 原文）。没有变更请求块时返回空串。"""
    blocks = fenced_blocks(text, "change_request")
    if not blocks:
        return "", ""
    raw = blocks[-1].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\b(scope|architecture)\b", raw, re.IGNORECASE)
        return (match.group(1).lower() if match else ""), raw
    impact = str((data or {}).get("impact") or "").strip().lower() if isinstance(data, dict) else ""
    if impact not in _IMPACTS or impact == "none":
        impact = ""
    return impact, raw


def accepted_ids(verdict: Verdict | None) -> set[str]:
    if verdict is None:
        return set()
    return {key for key, value in verdict.ac.items() if value == "pass"}


def split_outputs(body: str, outputs: list[str], *, optional: frozenset[str] = frozenset()) -> dict[str, str]:
    """一次调用产出多个产物时，按同名围栏块或同名标题切分。

    找不到切分标记的产物沿用整段正文；`optional` 中的产物找不到时为空。
    """
    if len(outputs) <= 1 and not (set(outputs) & optional):
        return {key: body for key in outputs}
    headings = list(_HEADING.finditer(body or ""))
    out: dict[str, str] = {}
    for key in outputs:
        blocks = fenced_blocks(body, key)
        if blocks:
            out[key] = blocks[-1].strip()
            continue
        section = _heading_section(body, headings, key)
        if section is not None:
            out[key] = section
        elif key in optional:
            out[key] = ""
        else:
            out[key] = body
    return out


def _heading_section(body: str, headings: list[re.Match[str]], key: str) -> str | None:
    for index, match in enumerate(headings):
        if match.group("name") != key:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        return body[match.end() : end].strip()
    return None
