"""启动时冻结场景与项目配置，供复盘对照当时的文件。"""

from __future__ import annotations

from auto_studio.config.context import resolve_scenario_and_project
from auto_studio.config.registry import get_project_yaml, get_scenario_yaml


def capture_config_snapshot(scenario_key: str = "", project_id: str = "") -> dict[str, str]:
    key, pid = resolve_scenario_and_project(scenario_key, project_id)
    scenario = get_scenario_yaml(key) if key else ""
    project = get_project_yaml(pid) if pid else ""
    return {
        "scenario_key": key,
        "project_id": pid,
        "config_snapshot_scenario": scenario,
        "config_snapshot_project": project,
    }
