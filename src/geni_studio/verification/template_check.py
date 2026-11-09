"""对照产物模板标题，列出正文缺失的章节。"""

from __future__ import annotations


def required_headings(template_text: str) -> list[str]:
    headings: list[str] = []
    for line in template_text.splitlines():
        if not line.startswith("#") or "{{" in line:
            continue
        title = line.lstrip("#").strip()
        if title and title not in headings:
            headings.append(title)
    return headings


def missing_headings(template_text: str, body: str) -> list[str]:
    return [title for title in required_headings(template_text) if title not in (body or "")]
