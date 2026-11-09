"""Run 显示名。默认是项目标识加递增序号，人也可以改。"""

from __future__ import annotations

import re
from typing import Any

from geni_studio.hitl.service import HitlError


def clean_run_name(raw: str) -> str:
    """整理输入。空字符串表示交给默认序号。"""
    name = " ".join(str(raw or "").split())
    if not name:
        return ""
    if len(name) > 64:
        raise HitlError("Run 命名不超过 64 个字符。")
    if any(ord(ch) < 32 or ch in "/\\" for ch in name):
        raise HitlError("Run 命名不能包含斜线或控制字符。")
    return name


def next_run_name(project_id: str, taken: set[str]) -> str:
    """项目标识加连字符和递增序号。已有 `_example-1`、`_example-3` 时下一个是 `_example-4`。"""
    prefix = project_id.strip()
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    highest = 0
    for name in taken:
        match = pattern.fullmatch(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1}"


def assign_run_name(project_id: str, requested: str, taken: set[str]) -> str:
    """空名称用下一个序号。默认格式若已被占用，也改用下一个序号。"""
    name = clean_run_name(requested)
    pid = project_id.strip()
    if not name:
        if not pid:
            return ""
        return next_run_name(pid, taken)
    pattern = re.compile(rf"^{re.escape(pid)}-(\d+)$") if pid else None
    if pattern is not None and pattern.fullmatch(name) and name in taken:
        return next_run_name(pid, taken)
    return name


def taken_names_for_project(records: list[tuple[str, dict[str, Any]]], project_id: str) -> set[str]:
    pid = project_id.strip()
    names: set[str] = set()
    for _thread_id, values in records:
        if str(values.get("project_id") or "").strip() != pid:
            continue
        name = str(values.get("run_name") or "").strip()
        if name:
            names.add(name)
    return names
