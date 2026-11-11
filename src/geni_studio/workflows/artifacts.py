"""产物读写：图状态已有字段直接读写，流程自定义的产物放在 `extra_artifacts`。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def state_fields() -> frozenset[str]:
    from geni_studio.workflows.default import FactoryState

    return frozenset(FactoryState.__annotations__)


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def is_custom(name: str) -> bool:
    return name not in state_fields()


def read(state: Mapping[str, Any], key: str) -> Any:
    if key in state_fields():
        return state.get(key)
    return (state.get("extra_artifacts") or {}).get(key)


def put(update: dict[str, Any], key: str, value: Any) -> None:
    """把一个产物写入节点返回的状态更新。"""
    if key in state_fields():
        update[key] = value
    else:
        update.setdefault("extra_artifacts", {})[key] = value


def unknown_names(names: Iterable[str], declared: Iterable[str]) -> list[str]:
    """既不是图状态字段、也不是本流程声明的自定义产物的名称。"""
    known = state_fields() | set(declared)
    return [name for name in names if name not in known]


def declared_custom(outputs: Iterable[str]) -> tuple[set[str], list[str]]:
    """流程显式声明的自定义产物，以及名称不合法的项。"""
    declared: set[str] = set()
    invalid: list[str] = []
    for name in outputs:
        if name in state_fields():
            continue
        if valid_name(name):
            declared.add(name)
        else:
            invalid.append(name)
    return declared, invalid


# 输入与日志类字段不作为产物登记。
_UNTRACKED = frozenset({"human_request", "baseline_log", "hitl_audit_log", "run_record"})


def produced(update: Mapping[str, Any]) -> dict[str, str]:
    """节点更新里新写出的产物正文。"""
    from geni_studio.workspace.persist import ARTIFACT_KEYS

    found = {
        key: value
        for key, value in update.items()
        if key in ARTIFACT_KEYS and key not in _UNTRACKED and isinstance(value, str) and value.strip()
    }
    extra = update.get("extra_artifacts")
    if isinstance(extra, dict):
        found.update({key: value for key, value in extra.items() if isinstance(value, str) and value.strip()})
    return found


def digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_artifact_dir(state: Mapping[str, Any], thread_id: str):
    from geni_studio.workspace.layout import run_dir_for_workspace

    run_dir = run_dir_for_workspace(str(state.get("workspace_path") or ""), thread_id)
    return run_dir / "artifacts" if run_dir is not None else None


def record(state: Mapping[str, Any], update: Mapping[str, Any], node_id: str, thread_id: str) -> dict[str, Any]:
    """登记本节点产出的产物（产出节点、第几次产出、摘要哈希），并在有运行目录时落盘全文。"""
    found = produced(update)
    if not found:
        return {}
    prior = state.get("artifact_meta") or {}
    folder = run_artifact_dir(state, thread_id) if thread_id else None
    meta: dict[str, dict[str, Any]] = {}
    for key, text in found.items():
        entry: dict[str, Any] = {
            "node": node_id,
            "attempt": int((prior.get(key) or {}).get("attempt") or 0) + 1,
            "sha256": digest(text),
            "chars": len(text),
        }
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{key}.md"
            path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            entry["path"] = str(path)
        meta[key] = entry
    return {"artifact_meta": meta}


def reference(state: Mapping[str, Any], key: str, label: str, *, role: str, value: Any = None) -> str:
    """提示词中的一份上游产物：可读文件的后端给出路径与摘要，其余内联全文。"""
    text = str(read(state, key) if value is None else value or "")
    if not text:
        return ""
    entry = (state.get("artifact_meta") or {}).get(key) or {}
    path = str(entry.get("path") or "")
    if path and entry.get("sha256") == digest(text) and _reads_files(role):
        from pathlib import Path

        if Path(path).is_file():
            return (
                f"{label}：全文在文件 {path}（{entry.get('chars', len(text))} 字，"
                f"sha256 {str(entry['sha256'])[:12]}，由 {entry.get('node', '')} 第 {entry.get('attempt', 1)} 次产出）。"
                "请先完整阅读该文件。"
            )
    return f"{label}：\n{text}"


def _reads_files(role: str) -> bool:
    from geni_studio.backends.runner import backend_reads_files

    return backend_reads_files(role)
