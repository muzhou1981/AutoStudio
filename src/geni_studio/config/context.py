"""四层配置栈合并与 RunContext。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from geni_studio.config.workflow_nodes import DEFAULT_GRAPH_NODES

DEFAULT_ARTIFACTS_DIR = "templates/artifacts"


class ConfigError(ValueError):
    """配置解析或校验失败。"""


def factory_root() -> Path:
    """GeniStudio 仓库根目录（含 scenarios/、projects/）。"""
    return Path(__file__).resolve().parents[3]


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


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _artifact_config(merged: dict[str, Any], name: str) -> dict[str, Any]:
    artifacts = merged.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return {}
    entry = artifacts.get(name) or {}
    return entry if isinstance(entry, dict) else {}


def _workflow_section(merged: dict[str, Any]) -> dict[str, Any]:
    wf = merged.get("workflow") or {}
    return wf if isinstance(wf, dict) else {}


def _features(wf: dict[str, Any]) -> dict[str, Any]:
    feat = wf.get("features") or {}
    return feat if isinstance(feat, dict) else {}


def _limits(wf: dict[str, Any]) -> dict[str, Any]:
    lim = wf.get("limits") or {}
    return lim if isinstance(lim, dict) else {}


def _validate_skip_nodes(skip_nodes: list[str]) -> None:
    unknown = [n for n in skip_nodes if n not in DEFAULT_GRAPH_NODES]
    if unknown:
        raise ConfigError(
            f"workflow.skip_nodes 含未知节点: {unknown}；"
            f"合法集合见 DEFAULT_GRAPH_NODES"
        )


@dataclass
class ResolvedTemplate:
    artifact_name: str
    template_path: Path
    omit_sections: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    """单次 Run 合并后的生效配置（L1+L2，不含 L3 state 补丁）。"""

    root: Path
    scenario_key: str
    project_id: str
    merged: dict[str, Any]
    scenario_path: Path | None = None
    project_path: Path | None = None

    @property
    def workflow(self) -> dict[str, Any]:
        return _workflow_section(self.merged)

    @property
    def profile_id(self) -> str:
        return str(self.workflow.get("profile_id") or "")

    @property
    def skip_nodes(self) -> frozenset[str]:
        raw = self.workflow.get("skip_nodes") or []
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(str(x) for x in raw)

    @property
    def artifacts_optional(self) -> frozenset[str]:
        raw = self.merged.get("artifacts_optional") or []
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(str(x) for x in raw)

    @property
    def max_dev_retries(self) -> int:
        lim = _limits(self.workflow)
        val = lim.get("max_dev_retries", 3)
        try:
            return int(val)
        except (TypeError, ValueError) as e:
            raise ConfigError("workflow.limits.max_dev_retries 须为整数") from e

    def feature_design_track_default(self) -> bool:
        return bool(_features(self.workflow).get("design_track", False))

    def feature_finance(self) -> bool:
        return bool(_features(self.workflow).get("finance", False))

    def is_node_enabled(self, node_name: str) -> bool:
        return node_name not in self.skip_nodes

    def config_plan_summary(self) -> str:
        lines = [
            f"scenario_key={self.scenario_key or '(未指定)'}",
            f"project_id={self.project_id or '(未指定)'}",
            f"profile_id={self.profile_id or '(未指定)'}",
            f"design_track_default={self.feature_design_track_default()}",
            f"skip_nodes={sorted(self.skip_nodes)}",
            f"artifacts_optional={sorted(self.artifacts_optional)}",
            f"max_dev_retries={self.max_dev_retries}",
        ]
        return "\n".join(lines)


def load_scenario_config(root: Path, scenario_key: str) -> tuple[dict[str, Any], Path]:
    if not scenario_key.strip():
        return {}, Path()
    key = scenario_key.strip()
    scenario_dir = root / "scenarios" / key
    scenario_file = scenario_dir / "scenario.yaml"
    profile_file = scenario_dir / "workflow_profile.yaml"
    if not scenario_file.is_file():
        raise ConfigError(f"未知 scenario_key={key!r}，缺少 {scenario_file}")
    merged = _load_yaml(scenario_file)
    if profile_file.is_file():
        merged = deep_merge(merged, _load_yaml(profile_file))
    merged.setdefault("scenario_key", key)
    return merged, scenario_file


def load_project_config(root: Path, project_id: str) -> tuple[dict[str, Any], Path]:
    if not project_id.strip():
        return {}, Path()
    pid = project_id.strip()
    project_file = root / "projects" / pid / "project.yaml"
    if not project_file.is_file():
        raise ConfigError(f"未知 project_id={pid!r}，缺少 {project_file}")
    return _load_yaml(project_file), project_file


def resolve_scenario_and_project(
    scenario_key: str = "",
    project_id: str = "",
    root: Path | None = None,
) -> tuple[str, str]:
    """若仅给 project_id，从 project.yaml 读取 scenario_key。"""
    root = root or factory_root()
    pid = project_id.strip()
    key = scenario_key.strip()
    if not key and pid:
        project_cfg, _ = load_project_config(root, pid)
        key = str(project_cfg.get("scenario_key") or "").strip()
    return key, pid


def build_run_context(
    *,
    scenario_key: str = "",
    project_id: str = "",
    root: Path | None = None,
) -> RunContext:
    root = root or factory_root()
    scenario_key, project_id = resolve_scenario_and_project(scenario_key, project_id, root)
    scenario_cfg, scenario_path = load_scenario_config(root, scenario_key)
    project_cfg, project_path = load_project_config(root, project_id)
    merged = deep_merge(scenario_cfg, project_cfg)
    skip_list = list(_workflow_section(merged).get("skip_nodes") or [])
    if skip_list:
        _validate_skip_nodes([str(x) for x in skip_list])
    return RunContext(
        root=root,
        scenario_key=(scenario_key or "").strip(),
        project_id=(project_id or "").strip(),
        merged=merged,
        scenario_path=scenario_path if scenario_path.is_file() else None,
        project_path=project_path if project_path.is_file() else None,
    )


def resolve_template(artifact_name: str, ctx: RunContext) -> ResolvedTemplate:
    """按 ADR 0002 决议 template_path。"""
    name = artifact_name.strip()
    if not name:
        raise ConfigError("artifact_name 不能为空")

    entry = _artifact_config(ctx.merged, name)
    omit = [str(x) for x in (entry.get("omit_sections") or [])]
    required = [str(x) for x in (entry.get("required_sections") or [])]

    explicit = (entry.get("template_path") or "").strip()
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = ctx.root / path
        if not path.is_file():
            raise ConfigError(f"artifacts.{name}.template_path 不存在: {path}")
        return ResolvedTemplate(name, path, omit, required)

    scenario_tpl = (
        ctx.root / "scenarios" / ctx.scenario_key / "templates" / f"{name}.md"
    )
    if ctx.scenario_key and scenario_tpl.is_file():
        return ResolvedTemplate(name, scenario_tpl, omit, required)

    default_tpl = ctx.root / DEFAULT_ARTIFACTS_DIR / f"{name}.md"
    if default_tpl.is_file():
        return ResolvedTemplate(name, default_tpl, omit, required)

    raise ConfigError(f"未找到产物 {name!r} 的模板（L0–L2 均无）")


def apply_omit_sections(markdown: str, omit_sections: list[str]) -> str:
    """按二级标题（## ）整节删除；标题须与 omit_sections 条目完全匹配（含 ##）。"""
    if not omit_sections:
        return markdown
    omit_set = set(omit_sections)
    lines = markdown.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            heading = line.rstrip("\n\r")
            skipping = heading in omit_set
        if not skipping:
            out.append(line)
    return "".join(out)


def load_template_text(resolved: ResolvedTemplate) -> str:
    text = resolved.template_path.read_text(encoding="utf-8")
    return apply_omit_sections(text, resolved.omit_sections)


def resolve_design_track(
    state: Mapping[str, Any],
    ctx: RunContext | None = None,
) -> bool:
    """L3 design_track_enabled > profile features.design_track > False。"""
    if "design_track_enabled" in state:
        return bool(state["design_track_enabled"])
    if ctx is None:
        key, pid = resolve_scenario_and_project(
            str(state.get("scenario_key") or ""),
            str(state.get("project_id") or ""),
        )
        ctx = build_run_context(scenario_key=key, project_id=pid)
    return ctx.feature_design_track_default()


def build_run_context_from_state(state: Mapping[str, Any]) -> RunContext:
    key, pid = resolve_scenario_and_project(
        str(state.get("scenario_key") or ""),
        str(state.get("project_id") or ""),
    )
    return build_run_context(scenario_key=key, project_id=pid)
