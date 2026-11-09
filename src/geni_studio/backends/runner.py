"""角色节点调用后端（Stub 或 Cursor SDK）。"""

from __future__ import annotations

from geni_studio.backends.base import StubBackend, get_default_backend
from geni_studio.backends.cost import current_project_id, note_cost
from geni_studio.config.context import ConfigError, factory_root, load_project_config
from geni_studio.roles.loader import load_role_system_prompt

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "developer": frozenset({"file_write", "shell"}),
    "tester": frozenset({"shell"}),
}


class CapabilityError(RuntimeError):
    """后端不具备角色所需能力。"""


def _role_config(role_name: str, project_id: str = "") -> dict:
    pid = (project_id or current_project_id()).strip()
    if not pid:
        return {}
    try:
        cfg, _ = load_project_config(factory_root(), pid)
    except ConfigError:
        return {}
    backends = cfg.get("backends")
    if not isinstance(backends, dict):
        return {}
    role_cfg = backends.get(role_name)
    return role_cfg if isinstance(role_cfg, dict) else {}


def model_for_role(role_name: str, project_id: str = "") -> str | None:
    model = str(_role_config(role_name, project_id).get("model") or "").strip()
    return model or None


def backend_for_role(role_name: str, project_id: str = ""):
    name = str(_role_config(role_name, project_id).get("backend") or "").strip().lower()
    if name == "stub":
        return StubBackend()
    if name == "cursor":
        from geni_studio.backends.cursor_backend import try_cursor_backend

        backend = try_cursor_backend()
        if backend is None:
            raise CapabilityError(f"{role_name} 配置为 cursor，但 Cursor 后端不可用")
        return backend
    return get_default_backend()


def invoke_role(
    *,
    role_name: str,
    user_prompt: str,
    stub_note: str,
    model: str | None = None,
) -> str:
    from geni_studio.hitl.control import (
        RunPaused,
        RunStopped,
        is_pause_requested,
        is_stop_requested,
    )

    if is_stop_requested():
        raise RunStopped("本轮已停止")
    if is_pause_requested():
        raise RunPaused("本轮已暂停")
    backend = backend_for_role(role_name)
    if isinstance(backend, StubBackend):
        note_cost(f"role={role_name} backend=stub cost=0")
        return f"[stub:{role_name}] {stub_note}"
    required = ROLE_CAPABILITIES.get(role_name, frozenset())
    have = getattr(backend, "capabilities", frozenset())
    missing = required - have
    if missing:
        raise CapabilityError(f"{role_name} 需要 {sorted(missing)}，后端未声明")
    chosen = model or model_for_role(role_name)
    system = load_role_system_prompt(role_name)
    text = backend.complete(
        role_name=role_name,
        system_prompt=system,
        user_prompt=user_prompt,
        model=chosen,
    )
    if is_pause_requested():
        raise RunPaused("本轮已暂停")
    return text
