"""角色能力的统一词表。角色所需能力只在 role.md 的 `capabilities` 中声明，后端声明同一词表。"""

from __future__ import annotations

from collections.abc import Iterable

READ_FILES = "read_files"
WRITE_FILES = "write_files"
RUN_COMMANDS = "run_commands"
MCP = "mcp"

ROLE_CAPABILITIES = (READ_FILES, WRITE_FILES, RUN_COMMANDS)
WORKSPACE_MUTATING = frozenset({WRITE_FILES, RUN_COMMANDS})

_LEGACY = {"file_read": READ_FILES, "file_write": WRITE_FILES, "shell": RUN_COMMANDS}


def normalize(words: Iterable[str] | str | None) -> frozenset[str]:
    """把能力声明归一到统一词表；兼容旧写法 `file_read`、`file_write`、`shell`。"""
    if words is None:
        return frozenset()
    if isinstance(words, str):
        words = [words]
    return frozenset(_LEGACY.get(str(item).strip(), str(item).strip()) for item in words if str(item).strip())
