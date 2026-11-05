#!/usr/bin/env bash
# 本地验收：单元测试 +（可选）飞书/Cursor smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi
"$PY" -m pytest -q
echo "--- cursor smoke ---"
"$PY" scripts/smoke_cursor_backend.py || true
BASE="${AUTO_STUDIO_WEB_BASE:-http://127.0.0.1:8765}"
if curl -sf -o /dev/null "$BASE/"; then
  echo "--- feishu smoke ($BASE) ---"
  AUTO_STUDIO_WEB_BASE="$BASE" "$PY" scripts/smoke_feishu_hitl.py
else
  echo "SKIP feishu smoke: $BASE 不可达（先运行 auto-studio-web）"
fi
