"""导入 Web 应用与默认图不得加载 `.env`、编译图或打开检查点库（C14）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_PROBE = """
import json, os
before = dict(os.environ)
import geni_studio.web.app
import geni_studio.workflows.default as default
from geni_studio.workspace import checkpoint
print(json.dumps({
    "env_changed": sorted(set(os.environ.items()) ^ set(before.items())),
    "graph_compiled": default._graph is not None,
    "sqlite_open": len(checkpoint._connections),
}))
"""


def test_importing_app_has_no_side_effects():
    env = {k: v for k, v in os.environ.items() if k != "GENI_STUDIO_CHECKPOINT"}
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True, env=env
    ).stdout
    result = json.loads(out.strip().splitlines()[-1])
    assert result == {"env_changed": [], "graph_compiled": False, "sqlite_open": 0}
