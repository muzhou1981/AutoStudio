"""pytest 默认 Stub 后端，并隔离开发机 `.env` 与 shell 中的运行时配置。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("GENI_STUDIO_CHECKPOINT", "memory")
os.environ.setdefault("GENI_STUDIO_WORKSPACE", "0")
os.environ.setdefault("GENI_STUDIO_SYNC_START", "1")


def _import_all_modules() -> None:
    """先导入全部模块：模块级 `from … import factory_root` 若在打桩期间首次执行，会把桩函数永久留在该模块里。"""
    import importlib
    import pkgutil

    import geni_studio

    for info in pkgutil.walk_packages(geni_studio.__path__, "geni_studio."):
        try:
            importlib.import_module(info.name)
        except ImportError:
            continue


_import_all_modules()

_ISOLATED_PREFIXES = ("LARK_", "CURSOR_", "GENI_STUDIO_FEISHU_", "OPENAI_", "CODEX_", "LANGSMITH_")
_ISOLATED_KEYS = (
    "GENI_STUDIO_LARK_BACKEND",
    "GENI_STUDIO_LARK_CLI_PATH",
    "GENI_STUDIO_PUBLIC_BASE_URL",
    "GENI_STUDIO_DEFAULT_MODEL",
    "GENI_STUDIO_CURSOR_MODEL",
    "GENI_STUDIO_CODEX_MODEL",
    "GENI_STUDIO_CURSOR_VERIFY",
    "GENI_STUDIO_TARGET_ROOT",
    "GENI_STUDIO_TEST_COMMAND",
    "GENI_STUDIO_GATE_TIMEOUT_SECONDS",
    "GENI_STUDIO_WEB_TOKEN",
    "GENI_STUDIO_WEB_OPERATOR",
)


@pytest.fixture(autouse=True)
def _isolate_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(_ISOLATED_PREFIXES) or key in _ISOLATED_KEYS:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "stub")
    monkeypatch.setenv("GENI_STUDIO_FEISHU_BRIDGE", "0")
    monkeypatch.setenv("GENI_STUDIO_FEISHU_WEBHOOK_INSECURE", "1")
    from geni_studio.backends.runner import reset_backend_cache

    reset_backend_cache()


@pytest.fixture
def example_retry_limit() -> int:
    """直接读取可编辑示例的期望值，检查服务/API 是否完整传递项目配置。"""
    from pathlib import Path

    import yaml

    project = Path(__file__).resolve().parents[1] / "projects" / "_example" / "project.yaml"
    return yaml.safe_load(project.read_text(encoding="utf-8"))["workflow"]["limits"]["max_dev_retries"]
