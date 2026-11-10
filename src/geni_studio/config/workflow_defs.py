"""可保存的流程定义。不改 LangGraph 默认图，也不改角色文件。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.context import ConfigError, factory_root
from geni_studio.config.identifiers import allocate_identifier
from geni_studio.roles.loader import role_contract, role_title

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
    "compliance",
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


def list_workflows(root: Path | None = None) -> list[dict[str, Any]]:
    base = (root or factory_root()) / "workflows"
    if not base.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/workflow.yaml")):
        data = _read_yaml(path)
        workflow_id = str(data.get("workflow_id") or path.parent.name)
        items.append(
            {
                "workflow_id": workflow_id,
                "title": str(data.get("title") or workflow_id),
                "builtin": bool(data.get("builtin")),
                "engine": str(data.get("engine") or ""),
                "subgraph": bool(data.get("subgraph")),
            }
        )
    items.sort(key=lambda item: (not item["builtin"], item["title"]))
    return items


def uses_current_branch(workflow_id: str, root: Path | None = None) -> bool:
    """自我改进直接改当前检出的分支，不另建工作树。"""
    if not workflow_id.strip() or not workflow_exists(workflow_id, root):
        return False
    if uses_default_engine(workflow_id, root):
        return False
    data = _read_yaml(_workflow_path(workflow_id, root, must_exist=True))
    return str(data.get("workspace") or "") == "current_branch"


def uses_default_engine(workflow_id: str, root: Path | None = None) -> bool:
    """内置的通用软件开发仍走 default.py，不按通用活动重编译。"""
    if not workflow_exists(workflow_id, root):
        return False
    data = _read_yaml(_workflow_path(workflow_id, root, must_exist=True))
    return str(data.get("engine") or "") == "default"


def workflow_activity_roles(workflow_id: str, root: Path | None = None) -> list[dict[str, str]]:
    """流程里实际会执行的活动角色。子流程和并行支路一并计入，人类不计入。"""
    labels = {item["id"]: item["label"] for item in list_role_lanes(root)}
    found: list[str] = []

    def walk(nodes: Any, stack: set[str]) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = str(node.get("kind") or "")
            if kind == "activity":
                role = str(node.get("role") or "").strip()
                if role and role != "human" and role not in found:
                    found.append(role)
            elif kind == "parallel":
                for branch in node.get("branches") or []:
                    if isinstance(branch, dict):
                        walk(branch.get("nodes"), stack)
            elif kind == "subgraph":
                subgraph_id = str(node.get("subgraph_id") or "").strip()
                if not subgraph_id or subgraph_id in stack:
                    continue
                try:
                    loaded = get_workflow(subgraph_id, root)
                except ConfigError:
                    continue
                walk(loaded["workflow"].get("nodes"), stack | {subgraph_id})

    loaded = get_workflow(workflow_id, root)
    walk(loaded["workflow"].get("nodes"), {workflow_id.strip()})
    return [{"id": role, "label": labels.get(role, role)} for role in found]


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


def import_workflow(text: str, root: Path | None = None) -> dict[str, Any]:
    """从 YAML 新建一份可编辑流程。内置标记和默认引擎不带入。标识被占用时另起一个。"""
    try:
        loaded = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError("原文不是合法的 YAML。") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("原文的根节点须为 mapping。")
    title = str(loaded.get("title") or "").strip()
    if not title:
        raise ConfigError("先写标题。")
    root = root or factory_root()
    taken = [item["workflow_id"] for item in list_workflows(root)]
    requested = str(loaded.get("workflow_id") or "").strip()
    if requested and _WORKFLOW_ID_RE.match(requested) and requested not in set(taken):
        workflow_id = requested
    else:
        workflow_id = allocate_identifier(title, prefix="workflow", taken=taken, translate=lambda _text: "")
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "title": title,
        "description": str(loaded.get("description") or "").strip(),
        "nodes": loaded.get("nodes") or [],
    }
    if loaded.get("subgraph"):
        payload["subgraph"] = True
    if str(loaded.get("workspace") or "") == "current_branch":
        payload["workspace"] = "current_branch"
    data = validate_workflow(payload, root=root, workflow_id=workflow_id)
    path = _workflow_path(workflow_id, root, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")
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


def copy_workflow(
    source_id: str,
    workflow_id: str,
    title: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """复制一份可编辑的流程。内置标记和默认引擎不带到副本。"""
    source = get_workflow(source_id, root)["workflow"]
    payload = {
        "workflow_id": workflow_id,
        "title": title.strip() or source.get("title") or workflow_id,
        "description": source.get("description") or "",
        "nodes": source.get("nodes") or [],
    }
    if source.get("subgraph"):
        payload["subgraph"] = True
    if str(source.get("workspace") or "") == "current_branch":
        payload["workspace"] = "current_branch"
    path = _workflow_path(workflow_id, root, must_exist=False)
    if path.is_file():
        raise ConfigError(f"已有同名流程：{workflow_id}")
    data = validate_workflow(payload, root=root, workflow_id=workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")
    return {"workflow": data, "yaml": _dump(data)}


def save_workflow(workflow_id: str, payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    path = _workflow_path(workflow_id, root, must_exist=True)
    current = _read_yaml(path)
    if current.get("builtin"):
        raise ConfigError("这是内置流程。要改，先复制一份。")
    data = validate_workflow(payload, root=root, workflow_id=workflow_id)
    if current.get("subgraph"):
        data["subgraph"] = True
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


def delete_workflow(workflow_id: str, root: Path | None = None) -> None:
    """删除 workflows/<id>/。内置流程不能删。不检查是否仍被其他流程当作子图引用。"""
    path = _workflow_path(workflow_id, root, must_exist=True)
    current = _read_yaml(path)
    if current.get("builtin"):
        raise ConfigError("这是内置流程，不能删除。")
    folder = path.parent.resolve()
    workflows_root = ((root or factory_root()) / "workflows").resolve()
    try:
        folder.relative_to(workflows_root)
    except ValueError as exc:
        raise ConfigError("只能删除工厂 workflows 目录下的流程。") from exc
    if folder == workflows_root:
        raise ConfigError("只能删除工厂 workflows 目录下的流程。")
    shutil.rmtree(folder)


def _require_subgraph(subgraph_id: str, owner: str, root: Path | None, seen_graphs: set[str]) -> None:
    if not subgraph_id:
        raise ConfigError("还没有选择子图。")
    if subgraph_id == owner or subgraph_id in seen_graphs:
        raise ConfigError("子图不能套住自己。")
    if not workflow_exists(subgraph_id, root):
        raise ConfigError(f"子图不存在：{subgraph_id}")
    if uses_default_engine(subgraph_id, root):
        raise ConfigError("通用软件开发不能当作子图插入。")
    data = _read_yaml(_workflow_path(subgraph_id, root, must_exist=True))
    nested = set(seen_graphs)
    nested.add(subgraph_id)
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("kind") or "") == "subgraph":
            _require_subgraph(str(node.get("subgraph_id") or ""), owner, root, nested)
        if str(node.get("kind") or "") != "parallel":
            continue
        for branch in node.get("branches") or []:
            if not isinstance(branch, dict):
                continue
            for child in branch.get("nodes") or []:
                if isinstance(child, dict) and str(child.get("kind") or "") == "subgraph":
                    _require_subgraph(str(child.get("subgraph_id") or ""), owner, root, nested)


def _clean_branches(
    raw: object,
    seen: set[str],
    roles: set[str],
    owner: str,
    root: Path | None,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ConfigError("并行至少要有两条支路。")
    branches: list[dict[str, Any]] = []
    branch_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ConfigError("支路须为 mapping。")
        branch_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not branch_id or branch_id in branch_ids:
            raise ConfigError("支路标识不能空，也不能重复。")
        branch_ids.add(branch_id)
        if not name:
            raise ConfigError("支路要写名称。")
        children = item.get("nodes")
        if not isinstance(children, list) or not children:
            raise ConfigError(f"「{name}」还没有活动。")
        cleaned_children: list[dict[str, Any]] = []
        for child in children:
            if not isinstance(child, dict):
                raise ConfigError(f"「{name}」里的步骤须为 mapping。")
            child_id = str(child.get("id") or "").strip()
            kind = str(child.get("kind") or "").strip()
            child_name = str(child.get("name") or "").strip()
            if not child_id or child_id in seen:
                raise ConfigError("节点标识不能空，也不能重复。")
            seen.add(child_id)
            if kind == "subgraph":
                subgraph_id = str(child.get("subgraph_id") or "").strip()
                if not child_name:
                    raise ConfigError("子图要写标题。")
                _require_subgraph(subgraph_id, owner, root, set())
                cleaned_children.append(
                    {
                        "id": child_id,
                        "kind": "subgraph",
                        "name": child_name,
                        "role": "",
                        "returns_to": "",
                        "subgraph_id": subgraph_id,
                    }
                )
            elif kind == "activity":
                role = str(child.get("role") or "").strip()
                if not child_name:
                    raise ConfigError("活动要写名称。")
                if role not in roles:
                    raise ConfigError(f"活动「{child_name}」要选择已有角色。")
                step: dict[str, Any] = {
                    "id": child_id,
                    "kind": "activity",
                    "name": child_name,
                    "role": role,
                    "returns_to": "",
                }
                if "inputs" in child:
                    step["inputs"] = _name_list(child.get("inputs"))
                if "outputs" in child:
                    step["outputs"] = _output_items(child.get("outputs"))
                cleaned_children.append(step)
            else:
                raise ConfigError(f"「{name}」里只能放活动或子图。")
        branches.append({"id": branch_id, "name": name, "nodes": cleaned_children})
    return branches


def save_as_subgraph(
    title: str,
    nodes: list[Any],
    description: str = "",
    *,
    workflow_id: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """把当前流程另存成可插入的子图。原流程不改。"""
    title = title.strip()
    if not title:
        raise ConfigError("先写子图标题。")
    root = root or factory_root()
    if not workflow_id:
        workflow_id = allocate_identifier(
            title,
            prefix="subgraph",
            taken=[item["workflow_id"] for item in list_workflows(root)],
        )
    path = _workflow_path(workflow_id, root, must_exist=False)
    if path.is_file():
        raise ConfigError(f"已有同名流程：{workflow_id}")
    data = validate_workflow(
        {
            "workflow_id": workflow_id,
            "title": title,
            "description": description,
            "nodes": nodes,
            "subgraph": True,
        },
        root=root,
        workflow_id=workflow_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")
    return {"workflow": data, "yaml": _dump(data)}


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
        max_loops = raw.get("max_loops")
        if not node_id or node_id in seen:
            raise ConfigError("节点标识不能空，也不能重复。")
        seen.add(node_id)
        if kind not in {"start", "end", "activity", "gate", "parallel", "subgraph"}:
            raise ConfigError(f"节点 {name or node_id} 的种类无法识别。")
        if kind == "start":
            name, role, returns_to, decision = "启动", "human", "", ""
        elif kind == "end":
            name, role, returns_to, decision = "结束", "human", "", ""
        elif kind == "parallel":
            if not name:
                raise ConfigError("并行要写名称。")
            role, returns_to, decision = "", "", ""
        elif kind == "subgraph":
            if not name:
                raise ConfigError("子图要写标题。")
            role, returns_to, decision = "", "", ""
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
        if raw.get("commits_on_branch") and role != "developer":
            raise ConfigError(f"活动「{name}」只有程序员可以提交入库。")
        item = {"id": node_id, "kind": kind, "name": name, "role": role, "returns_to": returns_to}
        if kind == "activity" and raw.get("commits_on_branch"):
            item["commits_on_branch"] = True
        if decision:
            item["decision"] = decision
        reject_to = str(raw.get("reject_to") or "").strip()
        if kind == "gate" and reject_to:
            item["reject_to"] = reject_to
        if returns_to:
            item["_max_loops"] = max_loops
        if kind == "activity":
            if "inputs" in raw:
                item["inputs"] = _name_list(raw.get("inputs"))
            if "outputs" in raw:
                item["outputs"] = _output_items(raw.get("outputs"))
        if kind == "subgraph":
            subgraph_id = str(raw.get("subgraph_id") or "").strip()
            _require_subgraph(subgraph_id, expected, root, seen_graphs=set())
            item["subgraph_id"] = subgraph_id
        if kind == "parallel":
            item["branches"] = _clean_branches(raw.get("branches"), seen, roles, expected, root)
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
        raw_loops = item.pop("_max_loops", None)
        if raw_loops in (None, ""):
            raise ConfigError(f"「{item['name']}」先写最大循环次数。")
        try:
            count = int(raw_loops)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"「{item['name']}」的最大循环次数要是整数。") from exc
        if isinstance(raw_loops, bool) or count < 1:
            raise ConfigError(f"「{item['name']}」的最大循环次数至少为 1。")
        item["max_loops"] = count
    for item in cleaned:
        reject = str(item.get("reject_to") or "")
        if not reject:
            continue
        if reject not in index or reject == item["id"]:
            raise ConfigError(f"「{item['name']}」的不通过去向要选已有节点。")
    result = {
        "workflow_id": expected,
        "title": str(payload.get("title") or expected).strip() or expected,
        "description": str(payload.get("description") or "").strip(),
        "nodes": cleaned,
    }
    if payload.get("builtin"):
        result["builtin"] = True
    if payload.get("subgraph"):
        result["subgraph"] = True
    engine = str(payload.get("engine") or "").strip()
    if engine:
        result["engine"] = engine
    workspace = str(payload.get("workspace") or "").strip()
    if workspace == "current_branch":
        result["workspace"] = workspace
    elif workspace:
        raise ConfigError("工作区只能声明为当前分支。")
    return result


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
