from pathlib import Path

from geni_studio.roles.loader import load_role_system_prompt, role_md_path


def test_role_md_path():
    p = role_md_path("project_manager", root=Path("/tmp/factory"))
    assert p == Path("/tmp/factory/roles/project_manager/role.md")


def test_load_project_manager_role():
    text = load_role_system_prompt("project_manager")
    assert "project_manager" in text.lower() or "项目经理" in text
