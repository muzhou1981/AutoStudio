"""由项目名、流程名、角色名生成稳定标识。

英文名称整理成小写并用 `-` 连接；名称含中文时用 prefix-1、prefix-2 这类序号。
不调用模型翻译：一次翻译要跑一轮 Agent，耗时十几秒到一分钟以上，会让“创建”长时间无响应。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def allocate_identifier(name: str, *, prefix: str, taken: Iterable[str]) -> str:
    """生成尚未占用的标识。名称含中文或整理后为空时使用 prefix-1、prefix-2。"""
    used = {item.strip() for item in taken if item and item.strip()}
    base = _base_from_name(name)
    if not _ID_RE.match(base):
        return _serial(prefix, used)
    return _unique(base, used)


def _base_from_name(name: str) -> str:
    text = (name or "").strip()
    if _ID_RE.match(text):
        return text
    if _CJK_RE.search(text):
        return ""
    return _slugify(text)


def _slugify(text: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", text or "")
    slug = "-".join(part.lower() for part in parts).strip("-")
    if not slug or not slug[0].isalpha():
        return ""
    return slug[:48].rstrip("-")


def _unique(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    number = 2
    while f"{base}-{number}" in used:
        number += 1
    return f"{base}-{number}"


def _serial(prefix: str, used: set[str]) -> str:
    number = 1
    while f"{prefix}-{number}" in used:
        number += 1
    return f"{prefix}-{number}"
