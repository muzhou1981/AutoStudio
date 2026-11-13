"""场景 / 项目配置的 Web 读写与列表（L1/L2 目录）。"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.context import (
    ConfigError,
    ConfigNotFound,
    build_run_context,
    factory_root,
)

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
        raise ConfigNotFound(f"未知 scenario_key={key!r}")
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
        raise ConfigNotFound(f"未知 project_id={pid!r}")
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
        raise ConfigError(f"项目不存在：{pid!r}（需 create=true）")
    if create and proj_dir.exists() and not pf.is_file():
        raise ConfigError(f"目录 projects/{pid}/ 已存在但无 project.yaml")

    proj_dir.mkdir(parents=True, exist_ok=True)
    pf.write_text(normalized, encoding="utf-8")

    scenario_key = str(data.get("scenario_key") or "")
    build_run_context(scenario_key=scenario_key, project_id=pid, root=root)


def delete_project(project_id: str, *, root: Path | None = None) -> None:
    """删除 projects/<id>/ 目录（须含 project.yaml）。"""
    root = root or factory_root()
    pid = project_id.strip()
    _validate_project_id(pid)
    proj_dir = _project_dir(root, pid)
    pf = proj_dir / "project.yaml"
    if not pf.is_file():
        raise ConfigNotFound(f"未知 project_id={pid!r}")
    projects_root = (root / "projects").resolve()
    resolved = proj_dir.resolve()
    try:
        resolved.relative_to(projects_root)
    except ValueError as exc:
        raise ConfigError("只能删除工厂 projects 目录下的项目。") from exc
    shutil.rmtree(proj_dir)


def list_directory_children(raw: str) -> dict[str, Any]:
    """列出服务进程能读取的子目录，供目录选择使用。"""
    from geni_studio.workspace.layout import _expand_workspace

    text = raw.strip()
    if text:
        path = _expand_workspace(text)
    else:
        path = Path.home().resolve()
    if not path.exists():
        raise ConfigError("目录不存在。")
    if not path.is_dir():
        raise ConfigError("要选择目录，不能是文件。")
    try:
        path = path.resolve()
        children = list(path.iterdir())
    except PermissionError as e:
        raise ConfigError("没有权限读取这个目录。") from e
    except OSError as e:
        raise ConfigError("读不到这个目录。") from e
    dirs: list[dict[str, str]] = []
    for child in children:
        try:
            if not child.is_dir():
                continue
            dirs.append({"name": child.name, "path": str(child.resolve())})
        except OSError:
            continue
    dirs.sort(key=lambda item: (item["name"].startswith("."), item["name"].casefold()))
    limit = 500
    parent = None if path.parent == path else str(path.parent)
    return {
        "path": str(path),
        "parent": parent,
        "dirs": dirs[:limit],
        "truncated": len(dirs) > limit,
    }


def list_directory_entries(raw: str) -> dict[str, Any]:
    """列出子目录和文件，供选择模板文件。"""
    from geni_studio.workspace.layout import _expand_workspace

    text = raw.strip()
    path = _expand_workspace(text) if text else Path.home().resolve()
    if not path.exists():
        raise ConfigError("目录不存在。")
    if not path.is_dir():
        raise ConfigError("要选择目录，不能是文件。")
    try:
        path = path.resolve()
        children = list(path.iterdir())
    except PermissionError as e:
        raise ConfigError("没有权限读取这个目录。") from e
    except OSError as e:
        raise ConfigError("读不到这个目录。") from e
    dirs: list[dict[str, str]] = []
    files: list[dict[str, str]] = []
    for child in children:
        try:
            item = {"name": child.name, "path": str(child.resolve())}
            if child.is_dir():
                dirs.append(item)
            elif child.is_file():
                files.append(item)
        except OSError:
            continue
    def _order(item: dict[str, str]) -> tuple[bool, str]:
        return (item["name"].startswith("."), item["name"].casefold())

    dirs.sort(key=_order)
    files.sort(key=_order)
    limit = 500
    dir_shown = dirs[:limit]
    file_shown = files[: max(0, limit - len(dir_shown))]
    parent = None if path.parent == path else str(path.parent)
    return {
        "path": str(path),
        "parent": parent,
        "dirs": dir_shown,
        "files": file_shown,
        "truncated": len(dirs) + len(files) > limit,
    }


def template_file_error(raw: str) -> str:
    """本地模板路径不可读时返回原因，可读时返回空字符串。"""
    text = (raw or "").strip()
    if not text:
        return "还没有选择本地文件。"
    path = Path(text).expanduser()
    if not path.is_absolute():
        return "本地文件要写绝对路径。"
    try:
        if not path.exists():
            return "文件不存在。"
        if not path.is_file():
            return "要选择文件，不能是目录。"
        if not os.access(path, os.R_OK):
            return "没有权限读取这个文件。"
    except OSError:
        return "读不到这个文件。"
    return ""


def describe_project_directory(raw: str, root: Path | None = None) -> dict[str, Any]:
    """从服务侧目录找出已绑定的项目，或给出可创建的标识。"""
    from geni_studio.workspace.layout import (
        _expand_workspace,
        _is_git_repo,
        workspace_config_error,
    )

    text = raw.strip()
    if not text:
        raise ConfigError("先填写目录。")
    error = workspace_config_error(text)
    if error:
        raise ConfigError(error)
    path = _expand_workspace(text)
    if not path.exists():
        raise ConfigError("目录不存在。")
    if not path.is_dir():
        raise ConfigError("工作区要填目录，不能是文件。")
    if not _is_git_repo(path):
        raise ConfigError("这个目录不是 git 仓库。换一个已有仓库，或先保存到空目录。")
    matches: list[str] = []
    for item in list_projects(root):
        workspace = project_workspace(item.project_id, root)
        if not workspace:
            continue
        try:
            if _expand_workspace(workspace) == path:
                matches.append(item.project_id)
        except OSError:
            continue
    suggested = path.name if _PROJECT_ID_RE.match(path.name) else ""
    return {
        "path": str(path),
        "project_ids": matches,
        "suggested_id": suggested,
        "remote_url": git_remote_url(path),
    }


def project_workspace(project_id: str, root: Path | None = None) -> str:
    """项目 YAML 里的待开发目录。未配置时返回空字符串。"""
    try:
        data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    except ConfigError:
        return ""
    return str(data.get("workspace") or "").strip()


def _apply_role_models(data: dict[str, Any], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    backends = _mapping(data.get("backends"))
    for role, model in raw.items():
        role_id = str(role).strip()
        if not role_id:
            continue
        cfg = _mapping(backends.get(role_id))
        chosen = str(model or "").strip()
        if chosen:
            cfg["model"] = chosen
            backends[role_id] = cfg
        else:
            cfg.pop("model", None)
            if cfg:
                backends[role_id] = cfg
            else:
                backends.pop(role_id, None)
    if backends:
        data["backends"] = backends
    else:
        data.pop("backends", None)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _role_models(data: dict[str, Any]) -> dict[str, str]:
    backends = _mapping(data.get("backends"))
    models: dict[str, str] = {}
    for role, raw in backends.items():
        cfg = _mapping(raw)
        model = str(cfg.get("model") or "").strip()
        if model:
            models[str(role)] = model
    return models


def project_form_view(project_id: str, root: Path | None = None) -> dict[str, Any]:
    """项目表单：选择项和单行字段。原文 YAML 仍走 get_project_yaml。"""
    from geni_studio.config.workflow_nodes import DEFAULT_GRAPH_NODES

    data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    workflow = _mapping(data.get("workflow"))
    features = _mapping(workflow.get("features"))
    limits = _mapping(workflow.get("limits"))
    feishu = _mapping(_mapping(data.get("hitl")).get("feishu"))
    from geni_studio.workspace.layout import resolve_target_root

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
        "remote_url": str(data.get("remote_url") or ""),
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
        "role_models": _role_models(data),
    }


def git_remote_url(path: Path) -> str:
    """读取仓库的 origin。没有 origin 时用第一个远端。地址不符合规则时返回空。"""
    import subprocess

    def _git(*args: str) -> str:
        try:
            proc = subprocess.run(
                ["git", "-C", str(path), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip()

    url = _git("remote", "get-url", "origin")
    if not url:
        names = [line.strip() for line in _git("remote").splitlines() if line.strip()]
        if names:
            url = _git("remote", "get-url", names[0])
    if not url or remote_url_error(url):
        return ""
    return url


def remote_url_error(raw: str) -> str | None:
    """空字符串表示不配置。返回给人看的错误，没有问题则返回 None。"""
    text = raw.strip()
    if not text:
        return None
    if any(ch.isspace() for ch in text):
        return "远程仓库地址不能含空白。"
    if text.startswith(("https://", "http://", "ssh://", "git://")):
        return None
    host = text.split("@", 1)[1] if text.startswith("git@") else ""
    if host and ":" in host and not host.startswith(":") and not host.endswith(":"):
        return None
    return "远程仓库要填 git 地址，例如 https://github.com/org/repo.git。"


def apply_project_form(
    project_id: str,
    fields: dict[str, Any],
    *,
    root: Path | None = None,
    require_profile: bool = False,
) -> str:
    """把表单写回 project.yaml，保留表单未覆盖的键。"""
    data = _parse_project_yaml_text(get_project_yaml(project_id, root))
    data["title"] = str(fields.get("title") or "").strip()
    data["description"] = str(fields.get("description") or "").strip()
    if "remote_url" in fields:
        remote_url = str(fields.get("remote_url") or "").strip()
        remote_error = remote_url_error(remote_url)
        if remote_error:
            raise ConfigError(remote_error)
        if remote_url:
            data["remote_url"] = remote_url
        else:
            data.pop("remote_url", None)
    data["scenario_key"] = str(fields.get("scenario_key") or "").strip()

    from geni_studio.workspace.layout import workspace_config_error

    workspace = str(fields.get("workspace") or "").strip()
    workspace_error = workspace_config_error(workspace)
    if workspace_error:
        raise ConfigError(workspace_error)
    if workspace:
        data["workspace"] = workspace
    else:
        data.pop("workspace", None)

    workflow = _mapping(data.get("workflow"))
    profile_id = str(fields.get("profile_id") or "").strip()
    if require_profile and not profile_id:
        raise ConfigError("先选择流程。")
    if profile_id:
        from geni_studio.config.workflow_defs import workflow_exists

        if not workflow_exists(profile_id, root):
            raise ConfigError("流程不存在。")
        workflow["profile_id"] = profile_id
    else:
        workflow.pop("profile_id", None)
    _apply_role_models(data, fields.get("role_models"))

    limits = _mapping(workflow.get("limits"))
    retries = fields.get("max_dev_retries")
    if retries is None or retries == "":
        limits.pop("max_dev_retries", None)
    else:
        try:
            limits["max_dev_retries"] = int(retries)
        except (TypeError, ValueError) as exc:
            raise ConfigError("开发重试上限要填整数，或留空沿用项目类型。") from exc
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
        "notices": list(ctx.notices),
    }


# Web 一期：仅报告密钥是否已配置，不回传明文
_SETTINGS_SECRET_KEYS = frozenset(
    {
        "CURSOR_API_KEY",
        "OPENAI_API_KEY",
        "LANGSMITH_API_KEY",
        "LARK_APP_SECRET",
    }
)
_SETTINGS_KEYS = (
    "CURSOR_API_KEY",
    "OPENAI_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
    "LARK_APP_ID",
    "LARK_APP_SECRET",
    "LARK_VERIFICATION_TOKEN",
    "LARK_ENCRYPT_KEY",
    "GENI_STUDIO_PUBLIC_BASE_URL",
    "GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID",
    "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID",
    "GENI_STUDIO_BACKEND",
    "GENI_STUDIO_CURSOR_MODEL",
    "GENI_STUDIO_CODEX_MODEL",
    "GENI_STUDIO_CODEX_REASONING_EFFORT",
    "GENI_STUDIO_DEFAULT_MODEL",
    "GENI_STUDIO_TARGET_ROOT",
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

    effective_vars = {**env_vars, **os.environ}
    _env_file_value_keys = {
        "GENI_STUDIO_PUBLIC_BASE_URL",
        "GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID",
        "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID",
        "GENI_STUDIO_BACKEND",
        "GENI_STUDIO_TARGET_ROOT",
    }

    def _setting_val(key: str) -> str:
        if key in _env_file_value_keys and key in env_vars:
            return env_vars[key]
        return effective_vars.get(key, "")

    explicit_backend = effective_vars.get("GENI_STUDIO_BACKEND", "").strip().lower()
    cursor_key = env_vars.get("CURSOR_API_KEY", "").strip() or os.environ.get(
        "CURSOR_API_KEY", ""
    ).strip()
    if explicit_backend in {"stub", "cursor", "codex"}:
        effective_backend = explicit_backend
    elif cursor_key:
        effective_backend = "cursor"
    else:
        effective_backend = "cursor"

    from geni_studio.hitl.feishu_config import resolve_lark_backend
    from geni_studio.hitl.lark_cli_client import auth_summary

    lark = auth_summary()
    backend = resolve_lark_backend(root)
    backend_labels = {
        "cursor": "Cursor SDK",
        "codex": "Codex SDK",
        "stub": "stub",
    }

    keys = []
    for name in _SETTINGS_KEYS:
        val = _setting_val(name)
        if name == "GENI_STUDIO_BACKEND":
            eff_label = backend_labels.get(effective_backend, effective_backend)
            hint = val or f"未设置（当前生效 {eff_label}）"
            keys.append({"name": name, "configured": bool(val), "value_hint": hint})
        elif name == "GENI_STUDIO_DEFAULT_MODEL":
            keys.append({
                "name": name,
                "configured": bool(val),
                "value_hint": val or "后端默认",
            })
        elif name == "GENI_STUDIO_CURSOR_MODEL":
            keys.append({
                "name": name,
                "configured": bool(val),
                "value_hint": val or "Auto（default）",
            })
        elif name in {"GENI_STUDIO_CODEX_MODEL", "GENI_STUDIO_CODEX_REASONING_EFFORT"}:
            keys.append({
                "name": name,
                "configured": bool(val),
                "value_hint": val or "Codex 默认",
            })
        elif name == "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID":
            entry: dict[str, Any] = {
                "name": name,
                "configured": bool(val),
                "value_hint": val,
            }
            if not val.strip() and lark.user_open_id:
                entry["value_hint"] = lark.user_open_id
                entry["suggested"] = True
            keys.append(entry)
        elif name in {
            "GENI_STUDIO_TARGET_ROOT",
            "GENI_STUDIO_PUBLIC_BASE_URL",
            "GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID",
        }:
            keys.append({"name": name, "configured": bool(val), "value_hint": val})
        elif name == "LANGSMITH_TRACING":
            keys.append({"name": name, "configured": True, "value_hint": val or "false"})
        elif name in _SETTINGS_SECRET_KEYS:
            effective = val or os.environ.get(name, "").strip()
            keys.append(
                {
                    "name": name,
                    "configured": bool(effective),
                    "value_hint": "已设置" if effective else "",
                    "secret_length": len(effective) if effective else 0,
                }
            )
        else:
            keys.append({"name": name, "configured": bool(val), "value_hint": "已设置" if val else ""})

    if backend == "lark_cli":
        note = (
            "飞书 HITL 走官方 lark-cli（Bot 凭据在 CLI 配置中，不必写 LARK_APP_SECRET）。"
            " 执行 lark-cli config init --new；项目 YAML 配置 hitl.feishu.notify_chat_id。"
        )
    else:
        note = (
            "飞书 HITL 走 env_bot：在 .env 填写 LARK_APP_ID / LARK_APP_SECRET。"
            " 或设 GENI_STUDIO_LARK_BACKEND=lark_cli 改用 lark-cli。"
        )

    keys.append(
        {
            "name": "GENI_STUDIO_LARK_BACKEND",
            "configured": bool(env_vars.get("GENI_STUDIO_LARK_BACKEND")),
            "value_hint": env_vars.get("GENI_STUDIO_LARK_BACKEND") or f"默认 {backend}",
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
            "user_open_id": lark.user_open_id,
            "user_name": lark.user_name,
        },
        "note": note,
    }
