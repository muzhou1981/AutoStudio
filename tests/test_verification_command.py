"""验证命令可配置、去除密钥、可选 bwrap 沙箱（D8）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from geni_studio.verification.command import (
    TestCommandError,
    resolve_test_command,
    run_test_command,
)


def _state(tmp_path: Path, **verification: object) -> dict:
    return {
        "workspace_path": str(tmp_path),
        "config_snapshot_effective": {"_test_command": "", "verification": verification},
    }


def test_project_allow_list_admits_make(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("test:\n\t@echo AC-1 ok\n", encoding="utf-8")
    with pytest.raises(TestCommandError, match="verification.allow"):
        resolve_test_command(_state(tmp_path, command="make test"))
    result = run_test_command(_state(tmp_path, command=["make", "test"], allow=["make"]))
    assert result is not None and result.returncode == 0
    assert "AC-1 ok" in result.transcript


def test_timeout_is_configurable(tmp_path: Path) -> None:
    import subprocess

    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    state = _state(tmp_path, command=f"python3 {script}", timeout_seconds=0.5)
    with pytest.raises(subprocess.TimeoutExpired):
        run_test_command(state)


def test_command_cannot_read_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "secret-cursor")
    monkeypatch.setenv("LARK_APP_SECRET", "secret-lark")
    monkeypatch.setenv("MY_SERVICE_TOKEN", "secret-token")
    monkeypatch.setenv("BUILD_FLAVOR", "release")
    script = tmp_path / "env.py"
    script.write_text("import os\nprint(sorted(k for k, v in os.environ.items() if v.startswith('secret-') or k == 'BUILD_FLAVOR'))\n")
    result = run_test_command(_state(tmp_path, command=f"python3 {script}"))
    assert result is not None
    assert "['BUILD_FLAVOR']" in result.transcript


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap 不可用")
def test_bwrap_sandbox_blocks_network_and_outside_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # /tmp 在沙箱内是独立的 tmpfs，探测文件须放在只读挂载的路径下。
    outside = Path(__file__).with_name(".bwrap_probe_outside")
    outside.unlink(missing_ok=True)
    script = workspace / "probe.py"
    script.write_text(
        "import socket\n"
        "open('inside.txt', 'w').write('ok')\n"
        "try:\n"
        f"    open({str(outside)!r}, 'w').write('x')\n"
        "    print('outside-writable')\n"
        "except OSError:\n"
        "    print('outside-readonly')\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "    print('network')\n"
        "except OSError:\n"
        "    print('no-network')\n",
        encoding="utf-8",
    )
    result = run_test_command(_state(workspace, command=f"python3 {script}", sandbox="bwrap"))
    assert result is not None and result.returncode == 0, result.transcript
    assert "outside-readonly" in result.transcript
    assert "no-network" in result.transcript
    assert (workspace / "inside.txt").read_text() == "ok"
    assert not outside.exists()
    outside.unlink(missing_ok=True)
