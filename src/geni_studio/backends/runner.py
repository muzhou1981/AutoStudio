"""角色节点调用后端（Stub、Cursor SDK 或 Codex SDK）。"""

from __future__ import annotations

from contextvars import ContextVar

from geni_studio.backends.base import (
    StubBackend,
    factory_default_model,
    get_default_backend,
)
from geni_studio.backends.cost import current_project_id, note_cost
from geni_studio.config.context import ConfigError, factory_root, load_project_config
from geni_studio.roles.loader import load_role_system_prompt

_role_models: ContextVar[dict[str, str] | None] = ContextVar("geni_studio_role_models", default=None)


def set_role_models(models: dict | None) -> object:
    clean: dict[str, str] = {}
    if isinstance(models, dict):
        for role, model in models.items():
            key = str(role).strip()
            value = str(model or "").strip()
            if key and value:
                clean[key] = value
    return _role_models.set(clean)


def reset_role_models(token: object) -> None:
    _role_models.reset(token)  # type: ignore[arg-type]


ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "developer": frozenset({"file_write", "shell"}),
    "tester": frozenset({"shell"}),
}


class CapabilityError(RuntimeError):
    """后端不具备角色所需能力。"""


def required_capabilities(role_name: str) -> frozenset[str]:
    from geni_studio.roles.loader import role_front_matter

    aliases = {"read_files": "file_read", "write_files": "file_write", "run_commands": "shell"}
    try:
        raw = role_front_matter(load_role_system_prompt(role_name)).get("capabilities") or []
    except FileNotFoundError:
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    return ROLE_CAPABILITIES.get(role_name, frozenset()) | frozenset(aliases.get(x, x) for x in raw)


def _role_config(role_name: str, project_id: str = "") -> dict:
    from geni_studio.backends.runtime import current_config

    frozen = current_config()
    if frozen is not None:
        return (frozen.get("backends") or {}).get(role_name) or {}
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
    chosen = str((_role_models.get() or {}).get(role_name) or "").strip()
    if chosen:
        return chosen
    model = str(_role_config(role_name, project_id).get("model") or "").strip()
    if model:
        return model
    backend = str(_role_config(role_name, project_id).get("backend") or "").strip().lower()
    return factory_default_model(backend) or None


def backend_for_role(role_name: str, project_id: str = ""):
    name = str(_role_config(role_name, project_id).get("backend") or "").strip().lower()
    from geni_studio.backends.runtime import current_config

    frozen = current_config()
    if not name and frozen is not None:
        name = str(frozen.get("_backend") or "")
    if name == "stub":
        return StubBackend()
    if name == "cursor":
        from geni_studio.backends.cursor_backend import try_cursor_backend

        backend = try_cursor_backend(force=True)
        if backend is None:
            raise CapabilityError(f"{role_name} 配置为 cursor，但 Cursor 后端不可用")
        return backend
    if name == "codex":
        from geni_studio.backends.codex_backend import CodexBackend

        try:
            import openai_codex  # noqa: F401
        except ImportError as exc:
            raise CapabilityError(f"{role_name} 配置为 codex，但未安装 openai-codex") from exc
        cfg = _role_config(role_name, project_id)
        return CodexBackend(
            sandbox=str(cfg.get("sandbox") or ""),
            timeout_seconds=cfg.get("timeout_seconds", 1800),
        )
    if name:
        raise CapabilityError(f"{role_name} 配置了未知后端：{name}")
    return get_default_backend()


def invoke_role(
    *,
    role_name: str,
    user_prompt: str,
    stub_note: str,
    model: str | None = None,
) -> str:
    from geni_studio.hitl.control import (
        RunStopped,
        is_stop_requested,
    )

    if is_stop_requested():
        raise RunStopped("本轮已停止")
    backend = backend_for_role(role_name)
    if isinstance(backend, StubBackend):
        note_cost(f"role={role_name} backend=stub cost=0")
        return f"[stub:{role_name}] {stub_note}"
    required = required_capabilities(role_name)
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
    return text
