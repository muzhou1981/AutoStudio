#!/usr/bin/env bash
# 在当前工作树上另起一个 GeniStudio 预览实例，供自举开发时用浏览器验证界面。
#
#   scripts/preview.sh [端口]     默认 8766；不允许 8765（正在使用的主服务）
#
# 预览实例与主服务隔离：运行工作树自己的源码（PYTHONPATH），检查点与运行库放在
# 工作树的 .geni_studio/preview/，后端固定为 stub，不消费飞书事件、不发通知，
# 不继承主服务的密钥。由某一轮 Agent 启动时，这一轮结束后随之回收。
set -euo pipefail

port="${1:-8766}"
if [[ "$port" == "8765" ]]; then
  echo "8765 是主服务端口，预览请用其他端口。" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel)"
common="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
python="${GENI_STUDIO_PYTHON:-}"
for candidate in "$root/.venv/bin/python" "$(dirname "$common")/.venv/bin/python"; do
  [[ -n "$python" ]] && break
  [[ -x "$candidate" ]] && python="$candidate"
done
python="${python:-python3}"

url="http://127.0.0.1:$port"
if curl -s --noproxy '*' -o /dev/null --max-time 2 "$url/"; then
  echo "端口 $port 已有服务在监听，换一个端口。" >&2
  exit 3
fi

state="$root/.geni_studio/preview"
mkdir -p "$state"
log="$state/server-$port.log"

env \
  -u CURSOR_API_KEY -u OPENAI_API_KEY -u CODEX_API_KEY \
  -u GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID -u GENI_STUDIO_FEISHU_NOTIFY_CHAT_ID \
  -u GENI_STUDIO_PUBLIC_BASE_URL -u GENI_STUDIO_LARK_BACKEND \
  PYTHONPATH="$root/src" \
  GENI_STUDIO_BACKEND=stub \
  GENI_STUDIO_FEISHU_BRIDGE=0 \
  GENI_STUDIO_CHECKPOINT=sqlite \
  GENI_STUDIO_CHECKPOINT_PATH="$state/checkpoints.sqlite" \
  nohup "$python" -m uvicorn geni_studio.web.app:app --host 127.0.0.1 --port "$port" \
  >"$log" 2>&1 &
pid=$!

for _ in $(seq 1 60); do
  if curl -s --noproxy '*' -o /dev/null --max-time 2 "$url/"; then
    echo "预览已启动：$url （pid $pid，日志 $log）"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "预览启动失败，日志如下：" >&2
    tail -n 40 "$log" >&2
    exit 1
  fi
  sleep 0.5
done
echo "预览 30 秒内未就绪，日志：$log" >&2
exit 1
