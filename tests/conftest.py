"""pytest 默认 Stub 后端，避免环境变量 CURSOR_API_KEY 影响单元测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AUTO_STUDIO_CHECKPOINT", "memory")
os.environ.setdefault("AUTO_STUDIO_WORKSPACE", "0")


@pytest.fixture(autouse=True)
def _force_stub_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_STUDIO_BACKEND", "stub")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
