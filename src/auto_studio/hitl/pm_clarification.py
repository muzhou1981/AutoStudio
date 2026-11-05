"""从 requirement_spec 解析 PM 澄清项，并合并人类答复。"""

from __future__ import annotations

import re

_SECTION_HEADERS = ("## 待澄清", "## PM 澄清", "## 澄清问题")
_CLARIFY_LINE = re.compile(r"^\s*CLARIFY:\s*(.+)\s*$", re.IGNORECASE)


def extract_pm_questions(requirement_spec: str) -> list[str]:
    text = (requirement_spec or "").strip()
    if not text:
        return []
    questions: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if any(h in stripped for h in _SECTION_HEADERS):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped:
            q = re.sub(r"^[-*]\s*", "", stripped)
            q = re.sub(r"^\d+[.)]\s*", "", q)
            if q:
                questions.append(q)
    for line in text.splitlines():
        m = _CLARIFY_LINE.match(line)
        if m:
            questions.append(m.group(1).strip())
    # 去重且保序
    seen: set[str] = set()
    out: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def merge_clarification_reply(
    requirement_spec: str,
    human_reply: str,
    questions: list[str] | None = None,
) -> str:
    base = (requirement_spec or "").rstrip()
    lines = ["", "## 人类澄清答复"]
    if questions:
        lines.append("（针对：" + "；".join(questions) + "）")
    lines.append(human_reply.strip())
    return base + "\n".join(lines) + "\n"
