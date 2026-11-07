"""可保存的流程定义。不改 LangGraph 默认图，也不改角色文件。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from auto_studio.config.context import ConfigError, factory_root
from auto_studio.roles.loader import role_contract, role_title

_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ROLE_ORDER = (
    "project_manager",
    "config_manager",
    "ux_designer",
    "ui_designer",
    "visual_designer",
    "architect",
    "developer",
    "code_reviewer",
    "tester",
    "qa",
    "process_owner",
    "finance",
)


def _name_list(value: object) -> list[str]:
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _output_items(value: object) -> list[dict[str, str]]:
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            name, source, template = item.strip(), "file", ""
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            source = str(item.get("source") or "file").strip()
            template = str(item.get("template") or "").strip()
            if source not in {"file", "link"}:
                source = "file"
        else:
            continue
        if name:
            items.append({"name": name, "source": source, "template": template})
    return items


def list_role_lanes(root: Path | None = None) -> list[dict[str, Any]]:
    """活动可选的角色。显示名用 role.md 的 title。人类放在最前，用来添加人工关卡。"""
    root = root or factory_root()
    base = root / "roles"
    found: dict[str, str] = {}
    if base.is_dir():
        for path in base.glob("*/role.md"):
            role_id = path.parent.name
            found[role_id] = role_title(path.read_text(encoding="utf-8"), role_id)
    ordered = [role_id for role_id in _ROLE_ORDER if role_id in found]
    ordered.extend(sorted(role_id for role_id in found if role_id not in _ROLE_ORDER))
    lanes: list[dict[str, Any]] = [{"id": "human", "label": "人类"}]
    for role_id in ordered:
        try:
            inputs, outputs = role_contract(role_id, root)
        except FileNotFoundError:
            inputs, outputs = [], []
        lanes.append(
            {"id": role_id, "label": found[role_id], "inputs": inputs, "outputs": outputs}
        )
    return lanes


def blank_workflow(workflow_id: str, title: str = "") -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "title": title.strip() or workflow_id,
        "description": "",
        "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ],
    }


def list_workflows(root: Path | None = None) -> list[dict[str, str]]:
    base = (root or factory_root()) / "workflows"
    if not base.is_dir():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(base.glob("*/workflow.yaml")):
        data = _read_yaml(path)
        workflow_id = str(data.get("workflow_id") or path.parent.name)
        items.append({"workflow_id": workflow_id, "title": str(data.get("title") or workflow_id)})
    return items


def workflow_exists(workflow_id: str, root: Path | None = None) -> bool:
    """profile_id 指向已保存的流程文件时才编译。旧的配置名没有这份文件。"""
    try:
        _check_id(workflow_id)
    except ConfigError:
        return False
    return _workflow_path(workflow_id, root, must_exist=False).is_file()


def get_workflow(workflow_id: str, root: Path | None = None) -> dict[str, Any]:
    path = _workflow_path(workflow_id, root, must_exist=True)
    data = validate_workflow(_read_yaml(path), root=root, workflow_id=workflow_id)
    return {"workflow": data, "yaml": _dump(data)}


def create_workflow(workflow_id: str, title: str = "", root: Path | None = None) -> dict[str, Any]:
    _check_id(workflow_id)
    path = _workflow_path(workflow_id, root, must_exist=False)
    if path.is_file():
        raise ConfigError(f"已有同名流程：{workflow_id}")
    data = validate_workflow(blank_workflow(workflow_id, title), root=root, workflow_id=workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")
    return {"workflow": data, "yaml": _dump(data)}


def save_workflow(workflow_id: str, payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    path = _workflow_path(workflow_id, root, must_exist=True)
    data = validate_workflow(payload, root=root, workflow_id=workflow_id)
    path.write_text(_dump(data), encoding="utf-8")
    return {"workflow": data, "yaml": _dump(data)}


def save_workflow_yaml(workflow_id: str, text: str, root: Path | None = None) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError("原文不是合法的 YAML。") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("原文的根节点须为 mapping。")
    return save_workflow(workflow_id, loaded, root=root)


def validate_workflow(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
    workflow_id: str = "",
) -> dict[str, Any]:
    """整理成可保存的流程。启动必须在最前，结束必须在最后。"""
    expected = workflow_id.strip() or str(payload.get("workflow_id") or "").strip()
    _check_id(expected)
    stated = str(payload.get("workflow_id") or "").strip()
    if stated and stated != expected:
        raise ConfigError("不能修改已有流程的标识。")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise ConfigError("流程至少要有启动和结束。")
    roles = {item["id"] for item in list_role_lanes(root) if item["id"] != "human"}
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ConfigError("节点须为 mapping。")
        node_id = str(raw.get("id") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        name = str(raw.get("name") or "").strip()
        role = str(raw.get("role") or "").strip()
        returns_to = str(raw.get("returns_to") or "").strip()
        decision = str(raw.get("decision") or "").strip()
        if not node_id or node_id in seen:
            raise ConfigError("节点标识不能空，也不能重复。")
        seen.add(node_id)
        if kind not in {"start", "end", "activity", "gate"}:
            raise ConfigError(f"节点 {name or node_id} 的种类无法识别。")
        if kind == "start":
            name, role, returns_to, decision = "启动", "human", "", ""
        elif kind == "end":
            name, role, returns_to, decision = "结束", "human", "", ""
        elif kind == "gate" or role == "human":
            if not name:
                raise ConfigError("决策点要写名称。")
            kind, role = "gate", "human"
        else:
            if not name:
                raise ConfigError("活动要写名称。")
            if role not in roles:
                raise ConfigError(f"活动「{name}」要选择已有角色。")
            decision = ""
        item = {"id": node_id, "kind": kind, "name": name, "role": role, "returns_to": returns_to}
        if decision:
            item["decision"] = decision
        if kind == "activity":
            if "inputs" in raw:
                item["inputs"] = _name_list(raw.get("inputs"))
            if "outputs" in raw:
                item["outputs"] = _output_items(raw.get("outputs"))
        cleaned.append(item)
    if cleaned[0]["kind"] != "start" or sum(item["kind"] == "start" for item in cleaned) != 1:
        raise ConfigError("启动必须有且只有一个，并且放在最前。")
    if cleaned[-1]["kind"] != "end" or sum(item["kind"] == "end" for item in cleaned) != 1:
        raise ConfigError("结束必须有且只有一个，并且放在最后。")
    index = {item["id"]: pos for pos, item in enumerate(cleaned)}
    for pos, item in enumerate(cleaned):
        target = item["returns_to"]
        if not target:
            continue
        if item["kind"] not in {"activity", "gate"}:
            raise ConfigError("只有活动和关卡可以回退。")
        if target not in index or index[target] >= pos or cleaned[index[target]]["kind"] == "end":
            raise ConfigError(f"「{item['name']}」的回退只能指向更早的节点。")
    return {
        "workflow_id": expected,
        "title": str(payload.get("title") or expected).strip() or expected,
        "description": str(payload.get("description") or "").strip(),
        "nodes": cleaned,
    }


def _check_id(workflow_id: str) -> None:
    if not _WORKFLOW_ID_RE.match(workflow_id):
        raise ConfigError("流程标识要以字母开头，后面只含字母、数字、_ 和 -。")


def _workflow_path(workflow_id: str, root: Path | None, *, must_exist: bool) -> Path:
    _check_id(workflow_id)
    path = (root or factory_root()) / "workflows" / workflow_id / "workflow.yaml"
    if must_exist and not path.is_file():
        raise ConfigError(f"流程不存在：{workflow_id}")
    return path


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("流程文件的根节点须为 mapping。")
    return data


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
