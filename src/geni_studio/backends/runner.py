"""角色节点调用后端（Stub、Cursor SDK 或 Codex SDK）。"""

from __future__ import annotations

import threading
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


_backend_lock = threading.Lock()
_codex_backends: dict[tuple[str, object], object] = {}


def reset_backend_cache() -> None:
    from geni_studio.backends.cursor_backend import reset_cursor_backend_cache

    with _backend_lock:
        _codex_backends.clear()
    reset_cursor_backend_cache()


class CapabilityError(RuntimeError):
    """后端不具备角色所需能力。"""


def required_capabilities(role_name: str) -> frozenset[str]:
    """角色所需能力，唯一来源是 role.md 的 `capabilities`。"""
    from geni_studio.roles.capabilities import normalize
    from geni_studio.roles.loader import role_front_matter

    try:
        raw = role_front_matter(load_role_system_prompt(role_name)).get("capabilities") or []
    except FileNotFoundError:
        raw = []
    return normalize(raw)


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


def effort_for_role(role_name: str, project_id: str = "") -> str:
    """本轮该角色的推理强度：Run 覆盖优先，其次项目配置；空串表示交给模型默认。"""
    from geni_studio.backends.reasoning import normalize_effort, reasoning_for_role

    configured = _role_config(role_name, project_id).get("reasoning_effort")
    return normalize_effort(reasoning_for_role(role_name, configured))


def backend_for_role(role_name: str, project_id: str = ""):
    import os

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
    if name == "codex" or (not name and os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() == "codex"):
        from geni_studio.backends.codex_backend import CodexBackend
        from geni_studio.backends.reasoning import fast_for_role, reasoning_for_role

        try:
            import openai_codex  # noqa: F401
        except ImportError as exc:
            raise CapabilityError(f"{role_name} 配置为 codex，但未安装 openai-codex") from exc
        cfg = _role_config(role_name, project_id)
        key = (
            str(cfg.get("sandbox") or ""),
            cfg.get("timeout_seconds", 1800),
            reasoning_for_role(role_name, cfg.get("reasoning_effort")),
            fast_for_role(role_name),
        )
        with _backend_lock:
            backend = _codex_backends.get(key)
            if backend is None:
                backend = CodexBackend(
                    sandbox=key[0], timeout_seconds=key[1], reasoning_effort=key[2], fast=key[3],
                )
                _codex_backends[key] = backend
        return backend
    if name:
        raise CapabilityError(f"{role_name} 配置了未知后端：{name}")
    return get_default_backend()


def backend_reads_files(role_name: str) -> bool:
    """该角色当前的后端能否自行读取文件；不能时提示词须内联产物全文。"""
    from geni_studio.roles.capabilities import normalize

    try:
        backend = backend_for_role(role_name)
    except CapabilityError:
        return False
    return "read_files" in normalize(getattr(backend, "capabilities", frozenset()))


def role_is_simulated(role_name: str) -> bool:
    """该角色当前是否由 Stub 后端模拟；模拟运行的结论只用于调试分支。"""
    try:
        return isinstance(backend_for_role(role_name), StubBackend)
    except CapabilityError:
        return False


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
    from geni_studio.roles.capabilities import normalize

    required = required_capabilities(role_name)
    have = normalize(getattr(backend, "capabilities", frozenset()))
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
