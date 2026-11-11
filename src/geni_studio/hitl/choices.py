"""从产物正文中抽取供人工点选的 A/B/C 式选项。"""

from __future__ import annotations

import re
from typing import Any

_OPTION_LINE = re.compile(
    r"^([A-Z])(?:[（(][^）)]*[)）])?\s*[：:.、]\s*(.+)$",
)


def option_letter(raw: str) -> str:
    """这一行若是「A：…」式选项，返回字母，否则返回空串。"""
    match = _OPTION_LINE.match(plain_line(raw))
    return match.group(1) if match else ""


def plain_line(raw: str) -> str:
    """去掉列表符号与加粗标记，供选项与题干识别。"""
    line = str(raw or "").strip()
    if line.startswith(("- ", "* ")):
        line = line[2:].strip()
    return line.replace("**", "").replace("__", "").strip()


def extract_choices(text: str) -> list[dict[str, Any]]:
    """识别「A（推荐）：…」类行；至少两条才视为有效选项组。"""
    if not str(text or "").strip():
        return []
    found: list[dict[str, Any]] = []
    for raw in str(text).splitlines():
        line = plain_line(raw)
        if not line or line.startswith("#"):
            continue
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
        line = plain_line(raw)
        if not line or line.startswith("#"):
            continue
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
    previous = ""
    for section in _sectionize(text):
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
            prompt = _prompt_from_section(part, choices) or _lead_in(previous)
            groups.append(
                {
                    "id": f"q{len(groups) + 1}",
                    "prompt": prompt,
                    "choices": choices,
                }
            )
        previous = section
    if not groups:
        flat = extract_choices(text)
        if len(flat) >= 2:
            groups.append({"id": "q1", "prompt": "", "choices": flat})
    return groups


def _lead_in(section: str) -> str:
    """选项单独成段时，紧邻的上一段若是一句题干，就用作题目。"""
    lines = [plain_line(raw) for raw in section.splitlines() if raw.strip()]
    if len(lines) != 1 or extract_choices(section) or len(lines[0]) > 200:
        return ""
    return lines[0].lstrip("#").strip()


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


_PICK = re.compile(r"(?:选择|选|同意|采用|按)\s*([A-Z])(?![A-Za-z])")


def choice_signature(group: dict[str, Any]) -> str:
    """同一组选项在会话、人工待办与飞书卡片之间的对应键。"""
    return "|".join(
        f"{item.get('id')}={item.get('label')}" for item in group.get("choices") or []
    )


def answers_from_reply(groups: list[dict[str, Any]], reply: str) -> dict[str, str]:
    """从人的答复里按题序认出所选字母，例如「选择 A（推荐）：…」「同意A」或单独一个「B」。"""
    text = str(reply or "").strip()
    letters = _PICK.findall(text)
    if not letters and re.fullmatch(r"[A-Z]", text):
        letters = [text]
    answers: dict[str, str] = {}
    for group in groups:
        ids = {str(item.get("id") or "") for item in group.get("choices") or []}
        while letters:
            letter = letters.pop(0)
            if letter in ids:
                answers[str(group.get("id") or "")] = letter
                break
    return answers
