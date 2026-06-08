#!/bin/bash
set -euo pipefail

TARGET_DIR="${HOME}/.function-router"
CONFIG_PATH="${TARGET_DIR}/config.json"
DEFAULT_OPENCLAW_CONFIG="${HOME}/.openclaw/openclaw.json"

prompt_default() {
  local prompt="$1"
  local default_value="$2"
  local value
  read -r -p "$prompt [$default_value]: " value
  if [ -z "$value" ]; then
    value="$default_value"
  fi
  printf '%s' "$value"
}

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Missing Function Router config: $CONFIG_PATH" >&2
  exit 1
fi

OPENCLAW_CONFIG=$(prompt_default "OpenClaw config path" "$DEFAULT_OPENCLAW_CONFIG")
if [ ! -f "$OPENCLAW_CONFIG" ]; then
  echo "OpenClaw config not found: $OPENCLAW_CONFIG" >&2
  exit 1
fi

BACKUP_PATH="${OPENCLAW_CONFIG}.bak.uninstall.$(date +%Y%m%d%H%M%S)"
cp "$OPENCLAW_CONFIG" "$BACKUP_PATH"

OPENCLAW_CONFIG="$OPENCLAW_CONFIG" \
CONFIG_PATH="$CONFIG_PATH" \
python3 -c '
import json
import os
from pathlib import Path

openclaw_path = Path(os.environ["OPENCLAW_CONFIG"])
config_path = Path(os.environ["CONFIG_PATH"])
openclaw = json.loads((openclaw_path.read_text(encoding="utf-8").strip() or "{}"))
config = json.loads(config_path.read_text(encoding="utf-8"))

# OpenClaw stores providers under models.providers (camelCase keys)
providers = openclaw.get("models", {}).get("providers", {})
providers.pop("function_router", None)
if "models" in openclaw:
    openclaw["models"]["providers"] = providers

# Find upstream provider to restore primary model
upstream = config.get("upstream", {})
upstream_model = upstream.get("model", "")
upstream_base_url = upstream.get("base_url", "")
provider_name = None
for name, provider in providers.items():
    if not isinstance(provider, dict):
        continue
    if provider.get("baseUrl") == upstream_base_url:
        provider_name = name
        break

# Primary model is under agents.defaults.model.primary
if provider_name and upstream_model:
    openclaw.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})["primary"] = f"{provider_name}/{upstream_model}"
elif upstream_model:
    openclaw.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})["primary"] = upstream_model

# Remove session-bridge plugin registration
plugins = openclaw.get("plugins", {})
allow = plugins.get("allow", [])
if "session-bridge" in allow:
    allow.remove("session-bridge")
entries = plugins.get("entries", {})
entries.pop("session-bridge", None)

openclaw_path.write_text(json.dumps(openclaw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'

REMOVE_DIR=$(prompt_default "Remove ${TARGET_DIR} directory? (y/N)" "N")
if [[ "$REMOVE_DIR" =~ ^[Yy]$ ]]; then
  rm -rf "$TARGET_DIR"
  REMOVED_TARGET="yes"
else
  REMOVED_TARGET="no"
fi

# Remove session-bridge plugin from extensions
PLUGIN_DST="${HOME}/.openclaw/extensions/session-bridge"
if [ -d "$PLUGIN_DST" ]; then
  rm -rf "$PLUGIN_DST"
  REMOVED_PLUGIN="yes"
else
  REMOVED_PLUGIN="no (not found)"
fi

echo
echo "Uninstall complete."
echo "OpenClaw config: $OPENCLAW_CONFIG"
echo "OpenClaw backup: $BACKUP_PATH"
echo "Removed provider: function_router"
echo "Restored primary model from upstream config where possible."
echo "Removed ${TARGET_DIR}: $REMOVED_TARGET"
echo "Removed session-bridge plugin: $REMOVED_PLUGIN"
