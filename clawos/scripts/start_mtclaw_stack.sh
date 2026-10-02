#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MTCLAW_REPO="${MTCLAW_REPO:-$(cd "$ROOT/.." && pwd)/MTClaw-框架代码}"

python3 "$ROOT/mtclaw/prepare_runtime.py"

export MTCLAW_ENABLED=true
export MTCLAW_BASE_URL="${MTCLAW_BASE_URL:-http://127.0.0.1:18791}"

python3 "$MTCLAW_REPO/function_router/server.py" \
  --config "$ROOT/mtclaw_runtime/config.json" &
MTCLAW_PID=$!

cleanup() {
  kill "$MTCLAW_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 30); do
  if curl --max-time 6 -fsS "$MTCLAW_BASE_URL/ready" >/dev/null; then
    break
  fi
  sleep 1
done

curl --max-time 6 -fsS "$MTCLAW_BASE_URL/ready" >/dev/null
# Keep the shell alive so its EXIT trap also stops the router when ClawOS exits.
python3 "$ROOT/clawos_server.py" --host 0.0.0.0 --port 18790
