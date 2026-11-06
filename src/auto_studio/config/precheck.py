"""启动前检查场景模板与领域资料。缺了就不进入图。"""

from __future__ import annotations

from pathlib import Path

from auto_studio.config.context import (
    ConfigError,
    RunContext,
    build_run_context,
    resolve_template,
)
from auto_studio.config.workflow_nodes import FINANCE_NODES
from auto_studio.hitl.rail import NODE_ARTIFACTS

_NOT_TEMPLATES = frozenset({"cost_ledger"})


def precheck_scenario_materials(
    scenario_key: str = "",
    project_id: str = "",
    *,
    root: Path | None = None,
) -> None:
    ctx = build_run_context(scenario_key=scenario_key, project_id=project_id, root=root)
    missing = [*_missing_templates(ctx), *_missing_materials(ctx)]
    if missing:
        raise ConfigError("场景材料未齐，不能启动。\n" + "\n".join(missing))


def _missing_templates(ctx: RunContext) -> list[str]:
    missing: list[str] = []
    optional = ctx.artifacts_optional
    finance = ctx.feature_finance()
    for node, artifacts in NODE_ARTIFACTS.items():
        if not ctx.is_node_enabled(node):
            continue
        if node in FINANCE_NODES and not finance:
            continue
        for name in artifacts:
            if name in optional or name in _NOT_TEMPLATES:
                continue
            try:
                resolved = resolve_template(name, ctx)
            except ConfigError as exc:
                missing.append(str(exc))
                continue
            if not resolved.template_path.is_file() or resolved.template_path.stat().st_size == 0:
                missing.append(f"产物模板为空：{name}")
    return missing


def _missing_materials(ctx: RunContext) -> list[str]:
    raw = ctx.merged.get("materials") or []
    if not isinstance(raw, list) or not ctx.scenario_key:
        return []
    scenario_dir = (ctx.root / "scenarios" / ctx.scenario_key).resolve()
    missing: list[str] = []
    for item in raw:
        rel = str(item or "").strip()
        if not rel:
            continue
        path = (scenario_dir / rel).resolve()
        if scenario_dir != path and scenario_dir not in path.parents:
            missing.append(f"领域资料越出场景目录：{rel}")
            continue
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(f"领域资料缺失或为空：{rel}")
    return missing
