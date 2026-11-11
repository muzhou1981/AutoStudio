"""从产物正文中抽取供人工点选的 A/B/C 式选项。"""

from __future__ import annotations

import re
from typing import Any

_OPTION_LINE = re.compile(
    r"^([A-Z])(?:[（(][^）)]*[)）])?\s*[：:.、]\s*(.+)$",
)


def extract_choices(text: str) -> list[dict[str, Any]]:
    """识别「A（推荐）：…」类行；至少两条才视为有效选项组。"""
    if not str(text or "").strip():
        return []
    found: list[dict[str, Any]] = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        match = _OPTION_LINE.match(line)
        if not match:
            continue
        letter = match.group(1)
        label = match.group(2).strip()
        if not label:
            continue
        recommended = "推荐" in raw
        found.append(
            {
                "id": letter,
                "label": label,
                "recommended": recommended,
            }
        )
    if len(found) < 2:
        return []
    return found


def choices_from_reading(sections: list[dict[str, str]]) -> list[dict[str, Any]]:
    """合并各阅读段落后去重（按 id），保留首次出现顺序。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in sections:
        for choice in extract_choices(str(section.get("body") or "")):
            cid = str(choice.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            merged.append(choice)
    if len(merged) < 2:
        return []
    return merged


_SECTION_BREAK = re.compile(
    r"^(?:\d+[\.、．)]\s*|问题\s*\d*[：:.]\s*|Q\d+[：:.]\s*|#{1,3}\s+)",
    re.MULTILINE,
)


def _prompt_from_section(section: str, choices: list[dict[str, Any]]) -> str:
    option_ids = {str(item.get("id") or "") for item in choices}
    lines: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        match = _OPTION_LINE.match(line)
        if match and match.group(1) in option_ids:
            continue
        if _SECTION_BREAK.match(line):
            cleaned = _SECTION_BREAK.sub("", line).strip()
            if cleaned:
                lines.append(cleaned)
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _sectionize(text: str) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", body) if chunk.strip()]
    if len(chunks) <= 1:
        return chunks
    return chunks


def extract_choice_groups(text: str) -> list[dict[str, Any]]:
    """按空行或题号拆成多道单选题，每题至少两条选项。"""
    groups: list[dict[str, Any]] = []
    for index, section in enumerate(_sectionize(text), start=1):
        nested = [
            piece.strip()
            for piece in re.split(
                r"(?m)(?=^\d+[\.、．)]\s*|^问题\s*\d*[：:.]|^Q\d+[：:.]|^#{1,3}\s+)",
                section,
            )
            if piece.strip()
        ]
        parts = nested if len(nested) > 1 else [section]
        for part in parts:
            choices = extract_choices(part)
            if len(choices) < 2:
                continue
            prompt = _prompt_from_section(part, choices)
            groups.append(
                {
                    "id": f"q{len(groups) + 1}",
                    "prompt": prompt,
                    "choices": choices,
                }
            )
    if not groups:
        flat = extract_choices(text)
        if len(flat) >= 2:
            groups.append({"id": "q1", "prompt": "", "choices": flat})
    return groups


def choice_groups_from_reading(sections: list[dict[str, str]]) -> list[dict[str, Any]]:
    """通读各段，按顺序汇总选择题组。"""
    groups: list[dict[str, Any]] = []
    for section in sections:
        title = str(section.get("title") or "").strip()
        body = str(section.get("body") or "")
        for group in extract_choice_groups(body):
            item = dict(group)
            if title and not item.get("prompt"):
                item["prompt"] = title
            elif title and item.get("prompt"):
                item["prompt"] = f"{title}\n{item['prompt']}".strip()
            item["id"] = f"q{len(groups) + 1}"
            groups.append(item)
    return groups


def choice_reply_line(choice: dict[str, Any]) -> str:
    """与 Web「采用并填入附言」一致的附言正文。"""
    letter = str(choice.get("id") or "").strip()
    label = str(choice.get("label") or "").strip()
    if not letter:
        return label
    if choice.get("recommended"):
        return f"选择 {letter}（推荐）：{label}"
    return f"选择 {letter}：{label}"
