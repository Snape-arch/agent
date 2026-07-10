#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CLAWOS_CONFIG_PATH="${CLAWOS_CONFIG_PATH:-$ROOT/config.competition.json}"
export MTCLAW_ENABLED=true
export MTCLAW_FALLBACK_ON_ERROR=false
export MODEL_PROVIDER="${MODEL_PROVIDER:-qwen}"
export MODEL_BASE_URL="${MODEL_BASE_URL:-http://127.0.0.1:8000/v1}"
export MODEL_REQUIRES_API_KEY="${MODEL_REQUIRES_API_KEY:-false}"

if [[ ! -f "$CLAWOS_CONFIG_PATH" ]]; then
  echo "Competition config not found: $CLAWOS_CONFIG_PATH" >&2
  exit 2
fi

exec bash "$ROOT/scripts/start_mtclaw_stack.sh"
