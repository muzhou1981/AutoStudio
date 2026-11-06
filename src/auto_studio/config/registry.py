"""场景 / 项目配置的 Web 读写与列表（L1/L2 目录）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from auto_studio.config.context import ConfigError, build_run_context, factory_root

_PROJECT_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"YAML 根节点须为 mapping: {path}")
    return data


@dataclass
class ScenarioSummary:
    scenario_key: str
    title: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "scenario_key": self.scenario_key,
            "title": self.title,
            "description": self.description,
        }


@dataclass
class ProjectSummary:
    project_id: str
    title: str
    description: str
    scenario_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "scenario_key": self.scenario_key,
        }


def _scenario_dir(root: Path, key: str) -> Path:
    return root / "scenarios" / key


def _project_dir(root: Path, project_id: str) -> Path:
    return root / "projects" / project_id


def list_scenarios(root: Path | None = None) -> list[ScenarioSummary]:
    root = root or factory_root()
    base = root / "scenarios"
    if not base.is_dir():
        return []
    out: list[ScenarioSummary] = []
    for path in sorted(base.iterdir()):
        if not path.is_dir():
            continue
        sf = path / "scenario.yaml"
        if not sf.is_file():
            continue
        data = _load_yaml(sf)
        key = str(data.get("scenario_key") or path.name)
        out.append(
            ScenarioSummary(
                scenario_key=key,
                title=str(data.get("title") or key),
                description=str(data.get("description") or ""),
            )
        )
    return out


def get_scenario_yaml(scenario_key: str, root: Path | None = None) -> str:
    root = root or factory_root()
    key = scenario_key.strip()
    sf = _scenario_dir(root, key) / "scenario.yaml"
    if not sf.is_file():
        raise ConfigError(f"未知 scenario_key={key!r}")
    return sf.read_text(encoding="utf-8")


def get_scenario_parsed(scenario_key: str, root: Path | None = None) -> dict[str, Any]:
    root = root or factory_root()
    return _load_yaml(_scenario_dir(root, scenario_key.strip()) / "scenario.yaml")


def list_projects(root: Path | None = None) -> list[ProjectSummary]:
    root = root or factory_root()
    base = root / "projects"
    if not base.is_dir():
        return []
    out: list[ProjectSummary] = []
    for path in sorted(base.iterdir()):
        if not path.is_dir():
            continue
        pf = path / "project.yaml"
        if not pf.is_file():
            continue
        data = _load_yaml(pf)
        pid = str(data.get("project_id") or path.name)
        out.append(
            ProjectSummary(
                project_id=pid,
                title=str(data.get("title") or pid),
                description=str(data.get("description") or ""),
                scenario_key=str(data.get("scenario_key") or ""),
            )
        )
    return out


def get_project_yaml(project_id: str, root: Path | None = None) -> str:
    root = root or factory_root()
    pid = project_id.strip()
    pf = _project_dir(root, pid) / "project.yaml"
    if not pf.is_file():
        raise ConfigError(f"未知 project_id={pid!r}")
    return pf.read_text(encoding="utf-8")


def _validate_project_id(project_id: str) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        raise ConfigError(
            "project_id 须以字母开头，仅含字母、数字、下划线与连字符"
        )


def _parse_project_yaml_text(yaml_text: str) -> dict[str, Any]:
    data = yaml.safe_load(yaml_text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("project.yaml 根节点须为 mapping")
    return data


def save_project_yaml(
    project_id: str,
    yaml_text: str,
    *,
    root: Path | None = None,
    create: bool = False,
) -> None:
    root = root or factory_root()
    pid = project_id.strip()
    _validate_project_id(pid)
    data = _parse_project_yaml_text(yaml_text)
    file_pid = str(data.get("project_id") or "").strip()
    if file_pid and file_pid != pid:
        raise ConfigError(f"YAML 内 project_id={file_pid!r} 与路径 {pid!r} 不一致")
    data.setdefault("project_id", pid)
    normalized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    proj_dir = _project_dir(root, pid)
    pf = proj_dir / "project.yaml"
    if not pf.is_file() and not create:
        raise ConfigError(f"项目不存在: {pid!r}（需 create=true）")
    if create and proj_dir.exists() and not pf.is_file():
        raise ConfigError(f"目录 projects/{pid}/ 已存在但无 project.yaml")

    proj_dir.mkdir(parents=True, exist_ok=True)
    pf.write_text(normalized, encoding="utf-8")

    scenario_key = str(data.get("scenario_key") or "")
    build_run_context(scenario_key=scenario_key, project_id=pid, root=root)


def project_workspace(project_id: str, root: Path | None = None) -> str:
    """项目 YAML 里的待开发目录。未配置时返回空字符串。"""
    try:
        data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    except ConfigError:
        return ""
    return str(data.get("workspace") or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def project_form_view(project_id: str, root: Path | None = None) -> dict[str, Any]:
    """项目表单：选择项和单行字段。原文 YAML 仍走 get_project_yaml。"""
    from auto_studio.config.workflow_nodes import DEFAULT_GRAPH_NODES

    data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    workflow = _mapping(data.get("workflow"))
    features = _mapping(workflow.get("features"))
    limits = _mapping(workflow.get("limits"))
    feishu = _mapping(_mapping(data.get("hitl")).get("feishu"))
    from auto_studio.workspace.layout import resolve_target_root

    design = features.get("design_track")
    if design is True:
        design_track_mode = "on"
    elif design is False:
        design_track_mode = "off"
    else:
        design_track_mode = "inherit"
    retries = limits.get("max_dev_retries")
    return {
        "project_id": project_id.strip(),
        "title": str(data.get("title") or ""),
        "description": str(data.get("description") or ""),
        "scenario_key": str(data.get("scenario_key") or ""),
        "profile_id": str(workflow.get("profile_id") or ""),
        "max_dev_retries": retries if isinstance(retries, int) else None,
        "design_track_mode": design_track_mode,
        "skip_mode": "custom" if "skip_nodes" in workflow else "inherit",
        "skip_nodes": [str(x) for x in (workflow.get("skip_nodes") or [])],
        "notify_chat_id": str(feishu.get("notify_chat_id") or ""),
        "notify_open_id": str(feishu.get("notify_open_id") or ""),
        "workspace": str(data.get("workspace") or ""),
        "workspace_resolved": str(resolve_target_root(project_id.strip())),
        "nodes": sorted(DEFAULT_GRAPH_NODES),
    }


def apply_project_form(
    project_id: str,
    fields: dict[str, Any],
    *,
    root: Path | None = None,
) -> str:
    """把表单写回 project.yaml，保留表单未覆盖的键。"""
    data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    data["title"] = str(fields.get("title") or "").strip()
    data["description"] = str(fields.get("description") or "").strip()
    data["scenario_key"] = str(fields.get("scenario_key") or "").strip()

    from auto_studio.workspace.layout import workspace_config_error

    workspace = str(fields.get("workspace") or "").strip()
    workspace_error = workspace_config_error(workspace)
    if workspace_error:
        raise ValueError(workspace_error)
    if workspace:
        data["workspace"] = workspace
    else:
        data.pop("workspace", None)

    workflow = _mapping(data.get("workflow"))
    profile_id = str(fields.get("profile_id") or "").strip()
    if profile_id:
        workflow["profile_id"] = profile_id
    else:
        workflow.pop("profile_id", None)

    limits = _mapping(workflow.get("limits"))
    retries = fields.get("max_dev_retries")
    if retries is None or retries == "":
        limits.pop("max_dev_retries", None)
    else:
        limits["max_dev_retries"] = int(retries)
    if limits:
        workflow["limits"] = limits
    else:
        workflow.pop("limits", None)

    features = _mapping(workflow.get("features"))
    mode = str(fields.get("design_track_mode") or "inherit")
    if mode == "on":
        features["design_track"] = True
    elif mode == "off":
        features["design_track"] = False
    else:
        features.pop("design_track", None)
    if features:
        workflow["features"] = features
    else:
        workflow.pop("features", None)

    if str(fields.get("skip_mode") or "inherit") == "custom":
        workflow["skip_nodes"] = [str(x) for x in (fields.get("skip_nodes") or [])]
    else:
        workflow.pop("skip_nodes", None)

    if workflow:
        data["workflow"] = workflow
    else:
        data.pop("workflow", None)

    hitl = _mapping(data.get("hitl"))
    feishu = _mapping(hitl.get("feishu"))
    chat_id = str(fields.get("notify_chat_id") or "").strip()
    open_id = str(fields.get("notify_open_id") or "").strip()
    if chat_id:
        feishu["notify_chat_id"] = chat_id
    else:
        feishu.pop("notify_chat_id", None)
    if open_id:
        feishu["notify_open_id"] = open_id
    else:
        feishu.pop("notify_open_id", None)
    if feishu:
        hitl["feishu"] = feishu
    else:
        hitl.pop("feishu", None)
    if hitl:
        data["hitl"] = hitl
    else:
        data.pop("hitl", None)

    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    save_project_yaml(project_id, text, root=root, create=False)
    return text


def effective_config_summary(
    *,
    scenario_key: str = "",
    project_id: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    ctx = build_run_context(
        scenario_key=scenario_key.strip(),
        project_id=project_id.strip(),
        root=root,
    )
    return {
        "scenario_key": ctx.scenario_key,
        "project_id": ctx.project_id,
        "profile_id": ctx.profile_id,
        "design_track_default": ctx.feature_design_track_default(),
        "skip_nodes": sorted(ctx.skip_nodes),
        "max_dev_retries": ctx.max_dev_retries,
        "config_plan_summary": ctx.config_plan_summary(),
    }


# Web 一期：仅报告密钥是否已配置，不回传明文
_SETTINGS_KEYS = (
    "CURSOR_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
    "LARK_APP_ID",
    "LARK_APP_SECRET",
    "LARK_VERIFICATION_TOKEN",
    "LARK_ENCRYPT_KEY",
    "AUTO_STUDIO_PUBLIC_BASE_URL",
    "AUTO_STUDIO_FEISHU_NOTIFY_CHAT_ID",
    "AUTO_STUDIO_FEISHU_NOTIFY_OPEN_ID",
    "AUTO_STUDIO_BACKEND",
    "AUTO_STUDIO_CURSOR_MODEL",
    "AUTO_STUDIO_TARGET_ROOT",
)


def settings_status(root: Path | None = None) -> dict[str, Any]:
    root = root or factory_root()
    env_path = root / ".env"
    env_vars: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    explicit_backend = env_vars.get("AUTO_STUDIO_BACKEND", "").strip().lower()
    if explicit_backend in {"stub", "cursor"}:
        effective_backend = explicit_backend
    elif env_vars.get("CURSOR_API_KEY", "").strip():
        effective_backend = "cursor"
    else:
        effective_backend = "stub"

    keys = []
    for name in _SETTINGS_KEYS:
        val = env_vars.get(name, "")
        if name == "AUTO_STUDIO_BACKEND":
            hint = val or f"未设置（当前生效 {effective_backend}）"
            keys.append({"name": name, "configured": bool(val), "value_hint": hint})
        elif name == "AUTO_STUDIO_CURSOR_MODEL":
            keys.append({
                "name": name,
                "configured": bool(val),
                "value_hint": val or "Auto（default）",
            })
        elif name in {
            "AUTO_STUDIO_TARGET_ROOT",
            "AUTO_STUDIO_PUBLIC_BASE_URL",
            "AUTO_STUDIO_FEISHU_NOTIFY_CHAT_ID",
            "AUTO_STUDIO_FEISHU_NOTIFY_OPEN_ID",
        }:
            keys.append({"name": name, "configured": bool(val), "value_hint": val})
        elif name == "LANGSMITH_TRACING":
            keys.append({"name": name, "configured": True, "value_hint": val or "false"})
        else:
            keys.append({"name": name, "configured": bool(val), "value_hint": "已设置" if val else ""})

    from auto_studio.hitl.feishu_config import resolve_lark_backend
    from auto_studio.hitl.lark_cli_client import auth_summary

    backend = resolve_lark_backend(root)
    lark = auth_summary()
    if backend == "lark_cli":
        note = (
            "飞书 HITL 走官方 lark-cli（Bot 凭据在 CLI 配置中，不必写 LARK_APP_SECRET）。"
            " 执行 lark-cli config init --new；项目 YAML 配置 hitl.feishu.notify_chat_id。"
        )
    else:
        note = (
            "飞书 HITL 走 env_bot：在 .env 填写 LARK_APP_ID / LARK_APP_SECRET。"
            " 或设 AUTO_STUDIO_LARK_BACKEND=lark_cli 改用 lark-cli。"
        )

    keys.append(
        {
            "name": "AUTO_STUDIO_LARK_BACKEND",
            "configured": bool(env_vars.get("AUTO_STUDIO_LARK_BACKEND")),
            "value_hint": env_vars.get("AUTO_STUDIO_LARK_BACKEND") or f"默认 {backend}",
        }
    )

    return {
        "env_file": str(env_path),
        "env_exists": env_path.is_file(),
        "effective_backend": effective_backend,
        "keys": keys,
        "lark_backend": backend,
        "lark_cli": {
            "installed": lark.installed,
            "config_ok": lark.config_ok,
            "bot_ready": lark.bot_ready,
            "hint": lark.hint,
        },
        "note": note,
    }
