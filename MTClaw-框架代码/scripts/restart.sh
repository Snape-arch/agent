#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
TARGET_DIR="${HOME}/.function-router"
CONFIG_PATH="${TARGET_DIR}/config.json"
PID_FILE="${TARGET_DIR}/function-router.pid"
LOG_FILE="${TARGET_DIR}/logs/router.out"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Missing config: $CONFIG_PATH" >&2
  exit 1
fi

PORT=$(CONFIG_PATH="$CONFIG_PATH" python3 -c '
import json
import os
from pathlib import Path

config = json.loads(Path(os.environ["CONFIG_PATH"]).read_text(encoding="utf-8"))
print(config["listen_port"])
')

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID"
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

for pid in $(pgrep -f "function_router.server --config|function-router --config" || true); do
  kill "$pid" 2>/dev/null || true
done

mkdir -p "$(dirname "$LOG_FILE")"
cd "$REPO_ROOT"

if command -v function-router >/dev/null 2>&1; then
  nohup function-router --config "$CONFIG_PATH" > "$LOG_FILE" 2>&1 &
else
  nohup python3 -m function_router.server --config "$CONFIG_PATH" > "$LOG_FILE" 2>&1 &
fi
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

HEALTH_URL="http://127.0.0.1:${PORT}/health"
for _ in $(seq 1 30); do
  if HEALTH_JSON=$(HEALTH_URL="$HEALTH_URL" python3 -c '
import json
import os
import urllib.request

url = os.environ["HEALTH_URL"]
with urllib.request.urlopen(url, timeout=2) as response:
    print(response.read().decode("utf-8"))
' 2>/dev/null); then
    TOOLS_LOADED=$(HEALTH_JSON="$HEALTH_JSON" python3 -c '
import json
import os

payload = json.loads(os.environ["HEALTH_JSON"])
print(payload.get("tools_loaded", 0))
')
    echo "Function Router restarted."
    echo "PID: $NEW_PID"
    echo "Health: $HEALTH_URL"
    echo "Tools loaded: $TOOLS_LOADED"
    exit 0
  fi
  sleep 1
done

echo "Function Router did not become healthy in time." >&2
echo "PID: $NEW_PID" >&2
echo "Log: $LOG_FILE" >&2
exit 1
