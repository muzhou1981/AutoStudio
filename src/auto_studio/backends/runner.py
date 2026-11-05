"""角色节点调用后端（Stub 或 Cursor SDK）。"""

from __future__ import annotations

from auto_studio.backends.base import StubBackend, get_default_backend
from auto_studio.roles.loader import load_role_system_prompt


def invoke_role(
    *,
    role_name: str,
    user_prompt: str,
    stub_note: str,
) -> str:
    backend = get_default_backend()
    if isinstance(backend, StubBackend):
        return f"[stub:{role_name}] {stub_note}"
    system = load_role_system_prompt(role_name)
    return backend.complete(
        role_name=role_name,
        system_prompt=system,
        user_prompt=user_prompt,
    )
