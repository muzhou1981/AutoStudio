"""由项目名、流程名生成稳定标识。中文名称译成英文后再整理。"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

Translate = Callable[[str], str]


def allocate_identifier(
    name: str,
    *,
    prefix: str,
    taken: Iterable[str],
    translate: Translate | None = None,
) -> str:
    """生成尚未占用的标识。翻译失败时使用 prefix-1、prefix-2。"""
    used = {item.strip() for item in taken if item and item.strip()}
    base = _base_from_name(name, translate if translate is not None else backend_translate)
    if not _ID_RE.match(base):
        return _serial(prefix, used)
    return _unique(base, used)


def backend_translate(text: str) -> str:
    """用当前配置的模型把名称译成英文单词。没有可用模型时返回空字符串。"""
    from geni_studio.backends.base import StubBackend, get_default_backend

    backend = get_default_backend()
    if isinstance(backend, StubBackend):
        return ""
    try:
        raw = backend.complete(
            role_name="identifier",
            system_prompt="把名称译成简短英文。只回复英文单词，词与词之间用空格。不要标点，不要解释。",
            user_prompt=text.strip(),
        )
    except Exception:  # noqa: BLE001 模型调用失败时改用序号，不阻止创建
        return ""
    line = (raw or "").strip().splitlines()[0] if raw else ""
    if not line or _CJK_RE.search(line):
        return ""
    return line


def _base_from_name(name: str, translate: Translate) -> str:
    text = (name or "").strip()
    if _ID_RE.match(text):
        return text
    if _CJK_RE.search(text):
        try:
            translated = translate(text) or ""
        except Exception:  # noqa: BLE001 翻译函数异常时改用序号
            translated = ""
        slug = _slugify(translated)
        if slug:
            return slug
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
