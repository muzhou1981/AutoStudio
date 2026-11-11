"""角色能力只来自 role.md：改 role.md 即改变能力检查与 Codex 沙箱。"""

from __future__ import annotations

import pytest

from geni_studio.backends.runner import (
    CapabilityError,
    invoke_role,
    required_capabilities,
)


def _role(root, name: str, capabilities: str) -> None:
    folder = root / "roles" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "role.md").write_text(
        f"---\ntitle: {name}\ncapabilities: {capabilities}\n---\n\n# {name}\n", encoding="utf-8"
    )


@pytest.fixture
def roles_root(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.roles.loader.factory_root", lambda: tmp_path)
    return tmp_path


def test_capabilities_come_only_from_role_md(roles_root):
    _role(roles_root, "developer", "[read_files]")
    assert required_capabilities("developer") == {"read_files"}
    _role(roles_root, "developer", "[read_files, write_files, run_commands]")
    assert required_capabilities("developer") == {"read_files", "write_files", "run_commands"}
    _role(roles_root, "legacy", "[file_write, shell]")
    assert required_capabilities("legacy") == {"write_files", "run_commands"}


def test_backend_without_capability_is_rejected(roles_root, monkeypatch):
    class ReadOnly:
        capabilities = frozenset({"read_files"})

        def complete(self, **_kwargs):
            return "ok"

    monkeypatch.setattr("geni_studio.backends.runner.backend_for_role", lambda _role: ReadOnly())
    _role(roles_root, "reviewer", "[read_files]")
    assert invoke_role(role_name="reviewer", user_prompt="看一下", stub_note="") == "ok"
    _role(roles_root, "reviewer", "[read_files, run_commands]")
    with pytest.raises(CapabilityError, match="run_commands"):
        invoke_role(role_name="reviewer", user_prompt="看一下", stub_note="")


def test_codex_sandbox_follows_role_md(roles_root):
    from geni_studio.backends.codex_backend import CodexBackend

    backend = CodexBackend.__new__(CodexBackend)
    backend._sandbox = None
    _role(roles_root, "developer", "[read_files]")
    assert backend.sandbox_for("developer") == "read-only"
    _role(roles_root, "auditor", "[read_files, write_files]")
    assert backend.sandbox_for("auditor") == "workspace-write"
