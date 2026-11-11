"""页面上的角色增加、修改和删除。仍写入 roles/<标识>/role.md。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.context import ConfigError, ConfigNotFound, factory_root
from geni_studio.roles.capabilities import ROLE_CAPABILITIES as _CAPABILITIES
from geni_studio.roles.loader import role_front_matter, role_md_path, role_title

ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("requirement_spec", "需求说明"),
    ("delivery_report", "交付报告"),
    ("testability_review", "可测性"),
    ("test_cases", "测试用例"),
    ("test_report", "测试报告"),
    ("config_plan", "配置计划"),
    ("baseline_log", "基线记录"),
    ("config_baseline", "交付基线"),
    ("config_retro", "配置复盘"),
    ("config_proposals", "配置提案"),
    ("budget_plan", "预算"),
    ("cost_report", "成本报告"),
    ("cost_ledger", "成本账本"),
    ("run_record", "运行记录"),
    ("ux_spec", "体验说明"),
    ("ui_spec", "界面规格"),
    ("visual_assets", "视觉资源"),
    ("architecture_design", "架构设计"),
    ("task_plan", "任务计划"),
    ("code_change", "代码变更"),
    ("change_request", "变更请求"),
    ("review_report", "评审意见"),
    ("qa_report", "质量报告"),
    ("compliance_report", "合规报告"),
    ("retro_report", "复盘"),
    ("process_proposals", "改进提案"),
)
_ARTIFACT_IDS = {item[0] for item in ARTIFACTS}
_CATEGORIES = {"management": "管理角色", "execution": "执行角色"}


def list_artifact_choices() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in ARTIFACTS]


def list_roles(root: Path | None = None) -> list[dict[str, str]]:
    root = root or factory_root()
    base = root / "roles"
    if not base.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for path in sorted(base.glob("*/role.md")):
        role_id = path.parent.name
        text = path.read_text(encoding="utf-8")
        data = role_front_matter(text)
        category = str(data.get("category") or "execution").strip()
        if category not in _CATEGORIES:
            category = "execution"
        rows.append(
            {
                "id": role_id,
                "title": role_title(text, role_id),
                "category": category,
            }
        )
    rows.sort(key=lambda item: item["title"])
    return rows


def get_role(role_id: str, root: Path | None = None) -> dict[str, Any]:
    root = root or factory_root()
    path = role_md_path(role_id, root)
    if not path.is_file():
        raise ConfigNotFound(f"角色不存在：{role_id}")
    text = path.read_text(encoding="utf-8")
    data = role_front_matter(text)
    category = str(data.get("category") or "execution").strip()
    if category not in _CATEGORIES:
        category = "execution"
    return {
        "id": role_id,
        "title": role_title(text, role_id),
        "category": category,
        "responsibilities": _strings(data.get("responsibilities")),
        "inputs": [item for item in _strings(data.get("inputs")) if item in _ARTIFACT_IDS],
        "outputs": [item for item in _strings(data.get("outputs")) if item in _ARTIFACT_IDS],
        "capabilities": [item for item in _strings(data.get("capabilities")) if item in _CAPABILITIES],
        "body": _body(text).strip(),
        "used_by": workflows_using_role(role_id, root),
    }


def create_role(title: str, root: Path | None = None) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ConfigError("先写标题。")
    root = root or factory_root()
    from geni_studio.config.identifiers import allocate_identifier

    role_id = allocate_identifier(
        title,
        prefix="role",
        taken=[item["id"] for item in list_roles(root)],
    )
    path = role_md_path(role_id, root)
    if path.exists():
        raise ConfigError(f"已有同名角色：{role_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _dump(
            {
                "id": role_id,
                "title": title,
                "category": "execution",
                "responsibilities": [],
                "inputs": [],
                "outputs": [],
                "capabilities": [],
                "body": "",
            }
        ),
        encoding="utf-8",
    )
    return get_role(role_id, root)


def save_role(role_id: str, payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or factory_root()
    path = role_md_path(role_id, root)
    if not path.is_file():
        raise ConfigNotFound(f"角色不存在：{role_id}")
    cleaned = _validate(role_id, payload)
    path.write_text(_dump(cleaned), encoding="utf-8")
    return get_role(role_id, root)


def delete_role(role_id: str, root: Path | None = None) -> None:
    root = root or factory_root()
    path = role_md_path(role_id, root)
    if not path.is_file():
        raise ConfigNotFound(f"角色不存在：{role_id}")
    used = workflows_using_role(role_id, root)
    if used:
        raise ConfigError(f"这个角色还在流程里：{'、'.join(used)}。先从这些流程里去掉。")
    path.unlink()
    parent = path.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


def workflows_using_role(role_id: str, root: Path | None = None) -> list[str]:
    """列出引用该角色的流程标题。包含并行支路，以及流程插入的子图。"""
    root = root or factory_root()
    base = root / "workflows"
    if not base.is_dir():
        return []
    titles: list[str] = []
    for path in sorted(base.glob("*/workflow.yaml")):
        data = _read_yaml(path)
        if not data:
            continue
        found = _roles_in_nodes(data.get("nodes"), root, set())
        if role_id in found:
            workflow_id = str(data.get("workflow_id") or path.parent.name)
            titles.append(str(data.get("title") or workflow_id))
    return titles


def _roles_in_nodes(nodes: object, root: Path, stack: set[str]) -> set[str]:
    found: set[str] = set()
    if not isinstance(nodes, list):
        return found
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = str(node.get("kind") or "")
        role = str(node.get("role") or "").strip()
        if kind == "activity" and role and role != "human":
            found.add(role)
        if kind == "parallel":
            for branch in node.get("branches") or []:
                if isinstance(branch, dict):
                    found.update(_roles_in_nodes(branch.get("nodes"), root, stack))
        if kind == "subgraph":
            subgraph_id = str(node.get("subgraph_id") or "").strip()
            if not subgraph_id or subgraph_id in stack:
                continue
            inner = _read_yaml(root / "workflows" / subgraph_id / "workflow.yaml")
            if inner:
                found.update(_roles_in_nodes(inner.get("nodes"), root, stack | {subgraph_id}))
    return found


def _validate(role_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ConfigError("先写标题。")
    category = str(payload.get("category") or "").strip()
    if category not in _CATEGORIES:
        raise ConfigError("先选择类别。")
    responsibilities = _strings(payload.get("responsibilities"))
    if not responsibilities:
        raise ConfigError("先写一条职责。")
    inputs = _artifact_list(payload.get("inputs"), empty_ok=True)
    outputs = _artifact_list(payload.get("outputs"), empty_ok=False)
    if not outputs:
        raise ConfigError("先选择一项输出。")
    capabilities = []
    for item in _strings(payload.get("capabilities")):
        if item not in _CAPABILITIES:
            raise ConfigError("能力无法识别。")
        if item not in capabilities:
            capabilities.append(item)
    body = str(payload.get("body") or "").strip()
    if not body:
        raise ConfigError("先写原则与价值观。")
    return {
        "id": role_id,
        "title": title,
        "category": category,
        "responsibilities": responsibilities,
        "inputs": inputs,
        "outputs": outputs,
        "capabilities": capabilities,
        "body": body,
    }


def _artifact_list(value: object, *, empty_ok: bool) -> list[str]:
    items = _strings(value)
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        if item not in _ARTIFACT_IDS:
            raise ConfigError(f"产物名无法识别：{item}")
        if item in seen:
            raise ConfigError("这个产物名重复了。")
        seen.add(item)
        cleaned.append(item)
    if not cleaned and not empty_ok:
        return []
    return cleaned


def _strings(value: object) -> list[str]:
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _body(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    return text[end + 4 :].lstrip("\n")


def _dump(role: dict[str, Any]) -> str:
    front = {
        "name": role["id"],
        "title": role["title"],
        "category": role["category"],
        "responsibilities": role["responsibilities"],
        "inputs": role["inputs"],
        "outputs": role["outputs"],
        "capabilities": role["capabilities"],
    }
    text = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    body = str(role.get("body") or "").strip()
    return f"---\n{text}\n---\n\n{body}\n" if body else f"---\n{text}\n---\n"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}
