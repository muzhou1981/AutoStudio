"""可保存的流程定义。不改 LangGraph 默认图，也不改角色文件。"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.context import ConfigError, ConfigNotFound, factory_root
from geni_studio.config.identifiers import allocate_identifier
from geni_studio.config.workflow_templates import (
    absorb_templates,
    import_from,
    prune_templates,
)
from geni_studio.roles.loader import role_contract, role_title

_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_LINK_RE = re.compile(r"^https?://", re.IGNORECASE)
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
            template = str(item.get("template") or "").strip()
            source = str(item.get("source") or "").strip()
            if source not in {"file", "link"}:
                source = "link" if _LINK_RE.match(template) else "file"
        else:
            continue
        if name:
            items.append({"name": name, "source": source, "template": template})
    return items


def _output_entries(value: object) -> list[str | dict[str, str]]:
    """保留只写名称的输出：它们取自角色契约，不带模板。"""
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        return []
    entries: list[str | dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            if item.strip():
                entries.append(item.strip())
        else:
            entries.extend(_output_items([item]))
    return entries


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
                "subgraph": bool(data.get("subgraph")),
                "hidden": bool(data.get("hidden")),
                "workspace": "current_branch" if data.get("workspace") == "current_branch" else "",
            }
        )
    items.sort(key=lambda item: (not item["builtin"], item["title"]))
    return items


def workflow_hidden(workflow_id: str, root: Path | None = None) -> bool:
    """隐藏的流程不出现在选择列表里，已选用它的项目照常运行。"""
    if not workflow_id.strip() or not workflow_exists(workflow_id, root):
        return False
    return bool(_read_yaml(_workflow_path(workflow_id, root, must_exist=True)).get("hidden"))


def uses_current_branch(workflow_id: str, root: Path | None = None) -> bool:
    """自我改进直接改当前检出的分支，不另建工作树。"""
    if not workflow_id.strip() or not workflow_exists(workflow_id, root):
        return False
    data = _read_yaml(_workflow_path(workflow_id, root, must_exist=True))
    return str(data.get("workspace") or "") == "current_branch"


def has_system_nodes(workflow_id: str, root: Path | None = None) -> bool:
    """系统节点、内置后处理和条件去向按节点标识书写，这类流程不能当作子图插入。"""
    if not workflow_exists(workflow_id, root):
        return False
    data = _read_yaml(_workflow_path(workflow_id, root, must_exist=True))
    return any(
        isinstance(node, dict)
        and (node.get("kind") == "system" or node.get("effect") or node.get("routes") or node.get("next"))
        for node in data.get("nodes") or []
    )


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
        workflow_id = allocate_identifier(title, prefix="workflow", taken=taken)
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
    validate_workflow(payload, root=root, workflow_id=workflow_id)
    path = _workflow_path(workflow_id, root, must_exist=False)
    data = validate_workflow(absorb_templates(payload, path.parent), root=root, workflow_id=workflow_id)
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
    if source.get("profile"):
        payload["profile"] = source["profile"]
    path = _workflow_path(workflow_id, root, must_exist=False)
    if path.is_file():
        raise ConfigError(f"已有同名流程：{workflow_id}")
    validate_workflow(payload, root=root, workflow_id=workflow_id)
    source_folder = _workflow_path(source_id, root, must_exist=True).parent
    payload["nodes"] = import_from(source_folder, payload["nodes"])
    data = validate_workflow(absorb_templates(payload, path.parent), root=root, workflow_id=workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")
    return {"workflow": data, "yaml": _dump(data)}


def save_workflow(workflow_id: str, payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    path = _workflow_path(workflow_id, root, must_exist=True)
    current = _read_yaml(path)
    if current.get("builtin"):
        raise ConfigError("这是内置流程。要改，先复制一份。")
    validate_workflow(payload, root=root, workflow_id=workflow_id)
    data = validate_workflow(absorb_templates(payload, path.parent), root=root, workflow_id=workflow_id)
    if current.get("subgraph"):
        data["subgraph"] = True
    try:
        original = validate_workflow(current, root=root, workflow_id=workflow_id)
    except ConfigError:
        original = current
    else:
        if current.get("subgraph"):
            original["subgraph"] = True
    _record_version(path, original, data)
    path.write_text(_dump(data), encoding="utf-8")
    prune_templates(path.parent)
    return {"workflow": data, "yaml": _dump(data)}


_VERSION_LIMIT = 50


def _version_files(path: Path) -> list[Path]:
    folder = path.parent / "versions"
    if not folder.is_dir():
        return []
    return sorted((item for item in folder.glob("*.yaml") if item.stem.isdigit()), key=lambda item: int(item.stem))


def _write_version(path: Path, number: int, data: dict[str, Any], saved_at: datetime) -> Path:
    target = path.parent / "versions" / f"{number}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"saved_at": saved_at.isoformat(timespec="seconds"), "workflow": data}
    target.write_text(_dump(record), encoding="utf-8")
    return target


def _read_version(item: Path) -> dict[str, Any]:
    record = _read_yaml(item)
    workflow = record.get("workflow")
    return {
        "version": int(item.stem),
        "saved_at": str(record.get("saved_at") or ""),
        "workflow": workflow if isinstance(workflow, dict) else {},
    }


def _record_version(path: Path, current: dict[str, Any], data: dict[str, Any]) -> None:
    """保存前写入版本记录：首次记录时先留下保存前的原样，内容未变不新增。"""
    files = _version_files(path)
    if not files:
        if current == data:
            return
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        files.append(_write_version(path, 1, current, mtime))
    if _read_version(files[-1])["workflow"] == data:
        return
    files.append(_write_version(path, int(files[-1].stem) + 1, data, datetime.now(UTC)))
    for item in files[:-_VERSION_LIMIT]:
        item.unlink(missing_ok=True)


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("name") or node.get("id") or "")


def _version_changes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    before = {node.get("id"): node for node in old.get("nodes") or [] if isinstance(node, dict)}
    after = {node.get("id"): node for node in new.get("nodes") or [] if isinstance(node, dict)}
    common = [key for key in after if key in before]
    return {
        "title": old.get("title") != new.get("title"),
        "description": old.get("description") != new.get("description"),
        "added": [_node_label(node) for key, node in after.items() if key not in before],
        "removed": [_node_label(node) for key, node in before.items() if key not in after],
        "changed": [_node_label(after[key]) for key in common if before[key] != after[key]],
        "reordered": [key for key in before if key in after] != common,
        "templates": _template_changes(old.get("nodes"), new.get("nodes")),
    }


def _template_refs(nodes: Any) -> dict[tuple[str, str], tuple[str, str]]:
    refs: dict[tuple[str, str], tuple[str, str]] = {}
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "parallel":
            for branch in node.get("branches") or []:
                if isinstance(branch, dict):
                    refs.update(_template_refs(branch.get("nodes")))
            continue
        for item in _output_items(node.get("outputs")):
            if item["template"]:
                refs[(str(node.get("id") or ""), item["name"])] = (_node_label(node), item["template"])
    return refs


def _template_changes(old: Any, new: Any) -> list[dict[str, str]]:
    """前后都有模板、但引用的文件或链接变了的输出。"""
    before, after = _template_refs(old), _template_refs(new)
    return [
        {"activity": label, "output": key[1]}
        for key, (label, template) in after.items()
        if key in before and before[key][1] != template
    ]


def list_workflow_versions(workflow_id: str, root: Path | None = None) -> list[dict[str, Any]]:
    """由新到旧列出版本；每项附上相对前一版本的改动，最早一项没有。"""
    path = _workflow_path(workflow_id, root, must_exist=True)
    records = [_read_version(item) for item in _version_files(path)]
    items = []
    for index, record in enumerate(records):
        workflow = record["workflow"]
        items.append({
            "version": record["version"],
            "saved_at": record["saved_at"],
            "title": str(workflow.get("title") or ""),
            "changes": _version_changes(records[index - 1]["workflow"], workflow) if index else None,
        })
    return list(reversed(items))


def get_workflow_version(workflow_id: str, version: int, root: Path | None = None) -> dict[str, Any]:
    path = _workflow_path(workflow_id, root, must_exist=True)
    for item in _version_files(path):
        if int(item.stem) == version:
            return _read_version(item)
    raise ConfigNotFound(f"流程 {workflow_id} 没有版本 {version}。")


def _subgraph_ids(nodes: Any) -> set[str]:
    found: set[str] = set()
    if not isinstance(nodes, list):
        return found
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "subgraph":
            subgraph_id = str(node.get("subgraph_id") or "").strip()
            if subgraph_id:
                found.add(subgraph_id)
        elif node.get("kind") == "parallel":
            for branch in node.get("branches") or []:
                if isinstance(branch, dict):
                    found |= _subgraph_ids(branch.get("nodes"))
    return found


def workflow_usage(workflow_id: str, root: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """选用这份流程的项目，以及把它当作子图直接插入的其他流程。"""
    root = root or factory_root()
    target = workflow_id.strip()
    projects: list[dict[str, str]] = []
    for path in sorted((root / "projects").glob("*/project.yaml")):
        try:
            data = _read_yaml(path)
        except (ConfigError, OSError, yaml.YAMLError):
            continue
        section = data.get("workflow")
        if isinstance(section, dict) and str(section.get("profile_id") or "").strip() == target:
            project_id = str(data.get("project_id") or path.parent.name)
            projects.append({"project_id": project_id, "title": str(data.get("title") or project_id)})
    workflows: list[dict[str, str]] = []
    for path in sorted((root / "workflows").glob("*/workflow.yaml")):
        try:
            data = _read_yaml(path)
        except (ConfigError, OSError, yaml.YAMLError):
            continue
        owner = str(data.get("workflow_id") or path.parent.name)
        if owner != target and target in _subgraph_ids(data.get("nodes")):
            workflows.append({"workflow_id": owner, "title": str(data.get("title") or owner)})
    return {"projects": projects, "workflows": workflows}


def delete_workflow(workflow_id: str, root: Path | None = None) -> None:
    """删除 workflows/<id>/。内置流程不能删；仍被项目选用或被其他流程当作子图时不能删。"""
    path = _workflow_path(workflow_id, root, must_exist=True)
    current = _read_yaml(path)
    if current.get("builtin"):
        raise ConfigError("这是内置流程，不能删除。")
    usage = workflow_usage(workflow_id, root)
    used = [f"项目“{item['title']}”" for item in usage["projects"]]
    used += [f"流程“{item['title']}”" for item in usage["workflows"]]
    if used:
        raise ConfigError(f"这个流程还在使用：{'、'.join(used)}。先改用别的流程或去掉子图。")
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
    if has_system_nodes(subgraph_id, root):
        raise ConfigError("含系统节点的流程（例如通用软件开发）不能当作子图插入。")
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


def _check_pick_pairs(cleaned: list[dict[str, Any]]) -> None:
    """对照择一的并行之后、下一个并行或结束之前，须有且只有一个“择一”决策点，见 ADR 0031。"""
    pending: dict[str, Any] | None = None
    for item in cleaned:
        if item["kind"] == "parallel" and pending is not None:
            raise ConfigError(f"并行“{pending['name']}”选了对照择一，要先放一个“择一”决策点，再开下一个并行。")
        if item["kind"] == "parallel" and item.get("join") == "compare":
            pending = item
        elif item["kind"] == "gate" and item.get("decision") == "pick":
            if pending is None:
                raise ConfigError(f"“{item['name']}”是择一决策点，但前面没有选了对照择一的并行。")
            pending = None
    if pending is not None:
        raise ConfigError(f"并行“{pending['name']}”选了对照择一，后面要有一个“择一”决策点。")


_MAX_GATE_ITEMS = 30


def _gate_items(raw: dict[str, Any], name: str, decision: str) -> dict[str, Any]:
    """决策点的决策项与汇总规则；没有决策项时返回空字典，见 ADR 0032。"""
    entries = raw.get("items")
    rule = str(raw.get("pass_rule") or "").strip()
    if entries in (None, "", []):
        if rule and rule != "all":
            raise ConfigError(f"决策点“{name}”没有决策项，不需要汇总规则。")
        return {}
    if decision == "pick":
        raise ConfigError(f"“{name}”是择一决策点，不能带决策项。")
    if not isinstance(entries, list):
        raise ConfigError(f"决策点“{name}”的决策项要写成列表。")
    if len(entries) > _MAX_GATE_ITEMS:
        raise ConfigError(f"决策点“{name}”的决策项最多 {_MAX_GATE_ITEMS} 项。")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"决策点“{name}”的每个决策项要有标识与名称。")
        item_id = str(entry.get("id") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not item_id or item_id in seen:
            raise ConfigError(f"决策点“{name}”的决策项标识不能空，也不能重复。")
        if not title:
            raise ConfigError(f"决策点“{name}”有决策项没写名称。")
        seen.add(item_id)
        item: dict[str, Any] = {"id": item_id, "title": title}
        hint = str(entry.get("hint") or "").strip()
        if hint:
            item["hint"] = hint
        if entry.get("required") is False:
            item["required"] = False
        items.append(item)
    if rule not in {"", "all", "manual"}:
        raise ConfigError(f"决策点“{name}”的汇总规则只能是全部通过才放行，或由人决定。")
    return {"items": items, "pass_rule": rule or "all"}


def _loop_count(raw_loops: object, name: str) -> int:
    if raw_loops in (None, ""):
        raise ConfigError(f"“{name}”先写最大循环次数。")
    try:
        count = int(raw_loops)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"“{name}”的最大循环次数要是整数。") from exc
    if isinstance(raw_loops, bool) or count < 1:
        raise ConfigError(f"“{name}”的最大循环次数至少为 1。")
    return count


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
            raise ConfigError(f"“{name}”还没有活动。")
        cleaned_children: list[dict[str, Any]] = []
        for child in children:
            if not isinstance(child, dict):
                raise ConfigError(f"“{name}”里的步骤须为 mapping。")
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
                    raise ConfigError(f"活动“{child_name}”要选择已有角色。")
                returns_to = str(child.get("returns_to") or "").strip()
                earlier = [item["id"] for item in cleaned_children if item["kind"] == "activity"]
                if returns_to and returns_to not in earlier:
                    raise ConfigError(f"“{child_name}”只能回退到支路“{name}”里更早的活动。")
                step: dict[str, Any] = {
                    "id": child_id,
                    "kind": "activity",
                    "name": child_name,
                    "role": role,
                    "returns_to": returns_to,
                }
                if returns_to:
                    step["max_loops"] = _loop_count(child.get("max_loops"), child_name)
                if "inputs" in child:
                    step["inputs"] = _name_list(child.get("inputs"))
                if "outputs" in child:
                    step["outputs"] = _output_items(child.get("outputs"))
                cleaned_children.append(step)
            else:
                raise ConfigError(f"“{name}”里只能放活动或子图。")
        branches.append({"id": branch_id, "name": name, "nodes": cleaned_children})
    return branches


def save_as_subgraph(
    title: str,
    nodes: list[Any],
    description: str = "",
    *,
    workflow_id: str = "",
    source_id: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """把当前流程另存成可插入的子图。原流程不改；原流程自带的模板复制到子图目录。"""
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
    payload = {
        "workflow_id": workflow_id,
        "title": title,
        "description": description,
        "nodes": nodes,
        "subgraph": True,
    }
    validate_workflow(payload, root=root, workflow_id=workflow_id)
    if source_id:
        payload["nodes"] = import_from(_workflow_path(source_id, root, must_exist=True).parent, nodes)
    data = validate_workflow(absorb_templates(payload, path.parent), root=root, workflow_id=workflow_id)
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
        if kind not in {"start", "end", "activity", "gate", "parallel", "subgraph", "system"}:
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
        elif kind == "system":
            if not name:
                raise ConfigError("系统节点要写名称。")
            if returns_to:
                raise ConfigError(f"系统节点“{name}”用 routes 声明去向，不能写回退。")
            decision = ""
        elif kind == "gate" or role == "human":
            if not name:
                raise ConfigError("决策点要写名称。")
            kind, role = "gate", "human"
        else:
            if not name:
                raise ConfigError("活动要写名称。")
            if role not in roles:
                raise ConfigError(f"活动“{name}”要选择已有角色。")
            decision = ""
        if raw.get("commits_on_branch") and role != "developer":
            raise ConfigError(f"活动“{name}”只有程序员可以提交入库。")
        item = {"id": node_id, "kind": kind, "name": name, "role": role, "returns_to": returns_to}
        if kind == "activity" and raw.get("commits_on_branch"):
            item["commits_on_branch"] = True
        if decision:
            item["decision"] = decision
        reject_to = str(raw.get("reject_to") or "").strip()
        if kind == "gate" and reject_to:
            item["reject_to"] = reject_to
        if kind == "gate":
            item.update(_gate_items(raw, name, decision))
        if returns_to:
            item["_max_loops"] = max_loops
        if kind == "activity":
            if "inputs" in raw:
                item["inputs"] = _name_list(raw.get("inputs"))
            if "outputs" in raw:
                item["outputs"] = _output_entries(raw.get("outputs"))
            primary = str(raw.get("primary_output") or "").strip()
            if primary:
                item["primary_output"] = primary
        if kind == "system":
            item.update(_system_fields(raw, name))
        if kind == "activity" and raw.get("when") not in (None, ""):
            item["when"] = _condition(raw.get("when"), name)
        if kind == "activity":
            item.update(_activity_fields(raw, name, returns_to))
        if kind == "subgraph":
            subgraph_id = str(raw.get("subgraph_id") or "").strip()
            _require_subgraph(subgraph_id, expected, root, seen_graphs=set())
            item["subgraph_id"] = subgraph_id
        if kind == "parallel":
            item["branches"] = _clean_branches(raw.get("branches"), seen, roles, expected, root)
            join = str(raw.get("join") or "merge").strip()
            if join not in {"merge", "compare"}:
                raise ConfigError(f"并行“{name}”的汇合方式只能是合并或对照择一。")
            if join == "compare":
                item["join"] = "compare"
        cleaned.append(item)
    if cleaned[0]["kind"] != "start" or sum(item["kind"] == "start" for item in cleaned) != 1:
        raise ConfigError("启动必须有且只有一个，并且放在最前。")
    if cleaned[-1]["kind"] != "end" or sum(item["kind"] == "end" for item in cleaned) != 1:
        raise ConfigError("结束必须有且只有一个，并且放在最后。")
    _check_pick_pairs(cleaned)
    index = {item["id"]: pos for pos, item in enumerate(cleaned)}
    for pos, item in enumerate(cleaned):
        target = item["returns_to"]
        if not target:
            continue
        if item["kind"] not in {"activity", "gate"}:
            raise ConfigError("只有活动和关卡可以回退。")
        if target not in index or index[target] >= pos or cleaned[index[target]]["kind"] == "end":
            raise ConfigError(f"“{item['name']}”的回退只能指向更早的节点。")
        item["max_loops"] = _loop_count(item.pop("_max_loops", None), item["name"])
    for item in cleaned:
        targets = [str(route["to"]) for route in item.get("routes") or []]
        if item.get("next"):
            targets.append(str(item["next"]))
        for target in targets:
            if target not in index or cleaned[index[target]]["kind"] == "start" or target == item["id"]:
                raise ConfigError(f"“{item['name']}”的去向“{target}”不是已有节点。")
    for item in cleaned:
        reject = str(item.get("reject_to") or "")
        if not reject:
            continue
        if reject not in index or reject == item["id"]:
            raise ConfigError(f"“{item['name']}”的不通过去向要选已有节点。")
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
    if str(payload.get("rail") or "") == "builtin":
        result["rail"] = "builtin"
    profile = _clean_profile(payload.get("profile"))
    if profile:
        result["profile"] = profile
    workspace = str(payload.get("workspace") or "").strip()
    if workspace == "current_branch":
        result["workspace"] = workspace
    elif workspace:
        raise ConfigError("工作区只能声明为当前分支。")
    return result


def _condition(raw: Any, name: str) -> Any:
    from geni_studio.workflows.system_nodes import condition_problem

    cond = [str(item).strip() for item in raw] if isinstance(raw, list) else str(raw).strip()
    problem = condition_problem(cond)
    if problem:
        raise ConfigError(f"“{name}”的条件不合法：{problem}")
    return cond


def _system_fields(raw: dict[str, Any], name: str) -> dict[str, Any]:
    from geni_studio.workflows.system_nodes import HANDLERS

    handler = str(raw.get("handler") or "").strip()
    if handler not in HANDLERS:
        raise ConfigError(f"系统节点“{name}”的实现“{handler}”不存在。")
    out: dict[str, Any] = {"handler": handler}
    if raw.get("when") not in (None, ""):
        out["when"] = _condition(raw.get("when"), name)
    out.update(_route_fields(raw, name))
    return out


def _activity_fields(raw: dict[str, Any], name: str, returns_to: str) -> dict[str, Any]:
    """活动的补充说明、内置后处理与条件去向。"""
    from geni_studio.workflows.system_nodes import EFFECTS

    out: dict[str, Any] = {}
    instruction = str(raw.get("instruction") or "").strip()
    if instruction:
        out["instruction"] = instruction
    effect = str(raw.get("effect") or "").strip()
    if effect:
        if effect not in EFFECTS:
            raise ConfigError(f"活动“{name}”的内置后处理“{effect}”不存在。")
        out["effect"] = effect
    routing = _route_fields(raw, name)
    if routing and returns_to:
        raise ConfigError(f"活动“{name}”已写回退，不能再用 routes 或 next 声明去向。")
    out.update(routing)
    return out


def _route_fields(raw: dict[str, Any], name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    routes = raw.get("routes")
    if routes not in (None, []):
        if not isinstance(routes, list):
            raise ConfigError(f"“{name}”的 routes 须为列表。")
        cleaned: list[dict[str, Any]] = []
        for route in routes:
            if not isinstance(route, dict) or not str(route.get("to") or "").strip() or not route.get("when"):
                raise ConfigError(f"“{name}”的每条路由都要写 when 和 to。")
            cleaned.append({"when": _condition(route["when"], name), "to": str(route["to"]).strip()})
        out["routes"] = cleaned
    nxt = str(raw.get("next") or "").strip()
    if nxt:
        out["next"] = nxt
    return out


def _clean_profile(raw: Any) -> dict[str, Any]:
    """流程的运行档案：features、gates 为开关，limits 为整数，skip_nodes 为节点列表，verification 原样保留。"""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("流程的 profile 须为 mapping。")
    unknown = sorted(set(raw) - {"features", "limits", "gates", "skip_nodes", "verification"})
    if unknown:
        raise ConfigError(f"流程的 profile 含无法识别的项：{'、'.join(unknown)}。")
    out: dict[str, Any] = {}
    for key in ("features", "gates"):
        section = raw.get(key)
        if section is None:
            continue
        if not isinstance(section, dict) or not all(isinstance(v, bool) for v in section.values()):
            raise ConfigError(f"profile.{key} 的每一项都要是 true 或 false。")
        out[key] = {str(k): v for k, v in section.items()}
    limits = raw.get("limits")
    if limits is not None:
        if not isinstance(limits, dict) or not all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in limits.values()
        ):
            raise ConfigError("profile.limits 的每一项都要是非负整数。")
        out["limits"] = {str(k): v for k, v in limits.items()}
    if "skip_nodes" in raw:
        out["skip_nodes"] = _name_list(raw.get("skip_nodes"))
    verification = raw.get("verification")
    if verification is not None:
        if not isinstance(verification, dict):
            raise ConfigError("profile.verification 须为 mapping。")
        out["verification"] = verification
    return out


def workflow_profile(workflow_id: str, root: Path | None = None) -> dict[str, Any]:
    """读取流程声明的运行档案；文件不合法时返回空档案，由启动或编译时报告错误。"""
    try:
        return dict(_clean_profile(_read_yaml(_workflow_path(workflow_id, root, must_exist=True)).get("profile")))
    except ConfigError:
        return {}


def _check_id(workflow_id: str) -> None:
    if not _WORKFLOW_ID_RE.match(workflow_id):
        raise ConfigError("流程标识要以字母开头，后面只含字母、数字、_ 和 -。")


def _workflow_path(workflow_id: str, root: Path | None, *, must_exist: bool) -> Path:
    _check_id(workflow_id)
    path = (root or factory_root()) / "workflows" / workflow_id / "workflow.yaml"
    if must_exist and not path.is_file():
        raise ConfigNotFound(f"流程不存在：{workflow_id}")
    return path


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("流程文件的根节点须为 mapping。")
    return data


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
