#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
TARGET_DIR="${HOME}/.function-router"
CONFIG_PATH="${TARGET_DIR}/config.json"
FUNCTIONS_PATH="${TARGET_DIR}/functions.jsonl"
SCRIPTS_DIR="${TARGET_DIR}/scripts"
LOGS_DIR="${TARGET_DIR}/logs"
DEFAULT_OPENCLAW_CONFIG="${HOME}/.openclaw/openclaw.json"

prompt_default() {
  local prompt_en="$1"
  local prompt_zh="$2"
  local default_value="$3"
  local value
  printf '%s [%s]\n' "$prompt_en" "$default_value" >&2
  printf '%s [%s]\n' "$prompt_zh" "$default_value" >&2
  read -r -p "> " value
  if [ -z "$value" ]; then
    value="$default_value"
  fi
  printf '%s' "$value"
}

prompt_required() {
  local prompt_en="$1"
  local prompt_zh="$2"
  local value
  while true; do
    printf '%s\n' "$prompt_en" >&2
    printf '%s\n' "$prompt_zh" >&2
    read -r -p "> " value
    if [ -n "$value" ]; then
      printf '%s' "$value"
      return 0
    fi
    echo "This field is required."
    echo "此项必填。"
  done
}

prompt_yes_no() {
  local prompt_en="$1"
  local prompt_zh="$2"
  local default_value="$3"
  local value
  local normalized_default
  normalized_default=$(printf '%s' "$default_value" | tr '[:upper:]' '[:lower:]')
  while true; do
    printf '%s [%s]\n' "$prompt_en" "$default_value" >&2
    printf '%s [%s]\n' "$prompt_zh" "$default_value" >&2
    read -r -p "> " value
    if [ -z "$value" ]; then
      value="$default_value"
    fi
    value=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')
    case "$value" in
      y|yes)
        printf 'yes'
        return 0
        ;;
      n|no)
        printf 'no'
        return 0
        ;;
    esac
    if [ "$value" = "$normalized_default" ]; then
      case "$normalized_default" in
        y|yes)
          printf 'yes'
          return 0
          ;;
        n|no)
          printf 'no'
          return 0
          ;;
      esac
    fi
    echo "Please answer yes or no."
    echo "请输入 yes 或 no。"
  done
}

DEFAULT_UPSTREAM_BASE_URL=""
DEFAULT_UPSTREAM_API_KEY=""
DEFAULT_UPSTREAM_MODEL=""
DEFAULT_UPSTREAM_SOURCE=""

OPENCLAW_CONFIG="$DEFAULT_OPENCLAW_CONFIG"
if [ -f "$OPENCLAW_CONFIG" ]; then
  DETECTED_PRIMARY=$(OPENCLAW_CONFIG="$OPENCLAW_CONFIG" python3 -c '
import json
import os
from pathlib import Path

path = Path(os.environ["OPENCLAW_CONFIG"])
try:
    raw = path.read_text(encoding="utf-8").strip() or "{}"
    data = json.loads(raw)
except Exception:
    print("", end="")
    raise SystemExit(0)

primary = data.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
print(primary, end="")
')
else
  DETECTED_PRIMARY=""
fi

if [ "$DETECTED_PRIMARY" = "function_router/function-router" ] && [ -f "$CONFIG_PATH" ]; then
  EXISTING_FR_UPSTREAM_INFO=$(CONFIG_PATH="$CONFIG_PATH" python3 -c '
import json
import os
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("", end="")
    raise SystemExit(0)

upstream = data.get("upstream", {})
base_url = upstream.get("base_url", "") if isinstance(upstream, dict) else ""
api_key = upstream.get("api_key", "") if isinstance(upstream, dict) else ""
model = upstream.get("model", "") if isinstance(upstream, dict) else ""
print(f"{base_url}\t{api_key}\t{model}", end="")
')
  IFS=$'\t' read -r DEFAULT_UPSTREAM_BASE_URL DEFAULT_UPSTREAM_API_KEY DEFAULT_UPSTREAM_MODEL <<< "$EXISTING_FR_UPSTREAM_INFO"
  if [ -n "$DEFAULT_UPSTREAM_BASE_URL" ] || [ -n "$DEFAULT_UPSTREAM_MODEL" ]; then
    DEFAULT_UPSTREAM_SOURCE="existing_fr"
  fi
fi

if [ -z "$DEFAULT_UPSTREAM_SOURCE" ] && [ -n "$DETECTED_PRIMARY" ]; then
  DEFAULT_UPSTREAM_INFO=$(OPENCLAW_CONFIG="$OPENCLAW_CONFIG" PRIMARY_MODEL="$DETECTED_PRIMARY" python3 -c '
import json
import os
from pathlib import Path

path = Path(os.environ["OPENCLAW_CONFIG"])
primary = os.environ["PRIMARY_MODEL"]
try:
    raw = path.read_text(encoding="utf-8").strip() or "{}"
    data = json.loads(raw)
except Exception:
    print("", end="")
    raise SystemExit(0)

provider_name = ""
model_name = primary
if "/" in primary:
    provider_name, model_name = primary.split("/", 1)

provider = data.get("models", {}).get("providers", {}).get(provider_name, {}) if provider_name else {}
base_url = provider.get("baseUrl", "") if isinstance(provider, dict) else ""
api_key = provider.get("apiKey", "") if isinstance(provider, dict) else ""
print(f"{base_url}\t{api_key}\t{model_name}", end="")
')
  IFS=$'\t' read -r DEFAULT_UPSTREAM_BASE_URL DEFAULT_UPSTREAM_API_KEY DEFAULT_UPSTREAM_MODEL <<< "$DEFAULT_UPSTREAM_INFO"
  if [ -n "$DEFAULT_UPSTREAM_BASE_URL" ] || [ -n "$DEFAULT_UPSTREAM_MODEL" ]; then
    DEFAULT_UPSTREAM_SOURCE="openclaw_primary"
  fi
fi

if [ -z "$DEFAULT_UPSTREAM_BASE_URL" ]; then
  DEFAULT_UPSTREAM_BASE_URL="https://api.openai.com/v1"
fi
if [ -z "$DEFAULT_UPSTREAM_MODEL" ]; then
  DEFAULT_UPSTREAM_MODEL="gpt-4o"
fi

USE_OPENCLAW_DEFAULT="no"
if [ "$DEFAULT_UPSTREAM_SOURCE" = "existing_fr" ]; then
  echo "Detected existing Function Router upstream config:"
  echo "检测到现有 Function Router 上游配置："
  if [ -n "$DEFAULT_UPSTREAM_BASE_URL" ]; then
    echo "  Base URL: $DEFAULT_UPSTREAM_BASE_URL"
    echo "  基础地址: $DEFAULT_UPSTREAM_BASE_URL"
  fi
  if [ -n "$DEFAULT_UPSTREAM_MODEL" ]; then
    echo "  Model: $DEFAULT_UPSTREAM_MODEL"
    echo "  模型: $DEFAULT_UPSTREAM_MODEL"
  fi
  echo
  USE_OPENCLAW_DEFAULT=$(prompt_yes_no "Use this existing Function Router upstream config as default?" "是否复用这份已有的 Function Router 上游配置？" "Y")
  echo
elif [ -n "$DETECTED_PRIMARY" ] && [ "$DETECTED_PRIMARY" != "function_router/function-router" ]; then
  echo "Detected OpenClaw primary model: $DETECTED_PRIMARY"
  echo "检测到当前 OpenClaw 主模型: $DETECTED_PRIMARY"
  if [ -n "$DEFAULT_UPSTREAM_BASE_URL" ]; then
    echo "  Base URL: $DEFAULT_UPSTREAM_BASE_URL"
    echo "  基础地址: $DEFAULT_UPSTREAM_BASE_URL"
  fi
  if [ -n "$DEFAULT_UPSTREAM_MODEL" ]; then
    echo "  Model: $DEFAULT_UPSTREAM_MODEL"
    echo "  模型: $DEFAULT_UPSTREAM_MODEL"
  fi
  echo
  USE_OPENCLAW_DEFAULT=$(prompt_yes_no "Use this current OpenClaw primary model as the upstream default?" "是否把当前 OpenClaw 主模型作为默认上游配置？" "Y")
  echo
fi

echo "Function Router installer"
echo "Function Router 安装器"
echo
echo "Function Router uses two LLM endpoints:"
echo "  1. Routing model — a local tool-calling model that decides whether to trigger a tool or pass through to the upstream LLM."
echo "  2. Upstream LLM — the main model that generates final user-facing responses. Requests are forwarded here when no tool is matched."
echo
echo "Function Router 会使用两个 LLM 端点："
echo "  1. 路由模型：本地工具调用模型，用来判断是否触发工具，还是转发给上游 LLM。"
echo "  2. 上游 LLM：负责生成最终面向用户的回复。当没有命中工具时，请求会转发到这里。"
echo

echo "── Routing model (local tool-calling model) ──"
echo "── 路由模型（本地工具调用模型） ──"
ROUTING_BASE_URL=$(prompt_default "  Base URL (OpenAI-compatible endpoint)" "  基础地址（兼容 OpenAI 的端点）" "https://api.example.com/v1")
ROUTING_MODEL=$(prompt_default "  Model name" "  模型名" "your-tool-calling-model")
ROUTING_API_KEY=$(prompt_default "  API key (use 'any' if no auth needed)" "  API key（如果不需要鉴权可填 any）" "${ROUTING_API_KEY:-any}")

echo
if [ "$USE_OPENCLAW_DEFAULT" = "yes" ]; then
  echo "── Upstream LLM (main response model) ──"
  echo "── 上游大模型（主回复模型） ──"
  echo "  Using detected upstream configuration as default."
  echo "  将使用检测到的上游配置作为默认值。"
  UPSTREAM_BASE_URL="$DEFAULT_UPSTREAM_BASE_URL"
  UPSTREAM_API_KEY="$DEFAULT_UPSTREAM_API_KEY"
  UPSTREAM_MODEL="$DEFAULT_UPSTREAM_MODEL"
  echo "  Base URL: $UPSTREAM_BASE_URL"
  echo "  基础地址: $UPSTREAM_BASE_URL"
  echo "  Model: $UPSTREAM_MODEL"
  echo "  模型: $UPSTREAM_MODEL"
  if [ -n "$UPSTREAM_API_KEY" ]; then
    echo "  API key: preserved from existing config"
    echo "  API 密钥: 已沿用现有配置"
  else
    UPSTREAM_API_KEY=$(prompt_required "  API key" "  API 密钥")
  fi
else
  echo "── Upstream LLM (main response model) ──"
  echo "── 上游大模型（主回复模型） ──"
  UPSTREAM_BASE_URL=$(prompt_default "  Base URL" "  基础地址" "$DEFAULT_UPSTREAM_BASE_URL")
  UPSTREAM_API_KEY=$(prompt_required "  API key" "  API 密钥")
  UPSTREAM_MODEL=$(prompt_default "  Model name" "  模型名" "$DEFAULT_UPSTREAM_MODEL")
fi

echo

echo "── General ──"
echo "── 通用配置 ──"
LISTEN_PORT=$(prompt_default "  FR listen port" "  FR 监听端口" "18790")
echo "  Tools base directory is the root path used by wrapper scripts via FR_TOOLS_BASE_DIR."
echo "  Example: if a script contains"
echo '    TOOL_PATH="${FR_TOOLS_BASE_DIR}/wallpaper-control/scripts/wallpaper-control.py"'
echo "  then set this to the directory that contains wallpaper-control/."
echo "  Example value: /home/mt/tools"
echo
echo "  Tools base directory 是 wrapper 脚本通过 FR_TOOLS_BASE_DIR 使用的根目录。"
echo "  示例：如果脚本里写了"
echo '    TOOL_PATH="${FR_TOOLS_BASE_DIR}/wallpaper-control/scripts/wallpaper-control.py"'
echo "  那这里就应填写包含 wallpaper-control/ 的目录。"
echo "  示例值: /home/mt/tools"
TOOLS_BASE_DIR=$(prompt_default "  Tools base directory" "  工具根目录" "$HOME/.function-router/scripts")
OPENCLAW_CONFIG=$(prompt_default "  OpenClaw config path" "  OpenClaw 配置路径" "$DEFAULT_OPENCLAW_CONFIG")

mkdir -p "$TARGET_DIR" "$SCRIPTS_DIR" "$LOGS_DIR"
cp "$REPO_ROOT/examples/config.example.json" "$CONFIG_PATH"
cp "$REPO_ROOT/examples/functions.example.jsonl" "$FUNCTIONS_PATH"
cp "$REPO_ROOT/examples/scripts/"*.sh "$SCRIPTS_DIR/"
chmod 755 "$SCRIPTS_DIR/"*.sh

PLUGIN_SRC="$REPO_ROOT/plugins/session-bridge"
PLUGIN_DST="${HOME}/.openclaw/extensions/session-bridge"
if [ -d "$PLUGIN_SRC" ]; then
  mkdir -p "$(dirname "$PLUGIN_DST")"
  rm -rf "$PLUGIN_DST"
  cp -r "$PLUGIN_SRC" "$PLUGIN_DST"
  echo "Installed session-bridge plugin to $PLUGIN_DST"
  echo "已安装 session-bridge 插件到 $PLUGIN_DST"
fi

ROUTING_BASE_URL="$ROUTING_BASE_URL" \
ROUTING_MODEL="$ROUTING_MODEL" \
ROUTING_API_KEY="$ROUTING_API_KEY" \
UPSTREAM_BASE_URL="$UPSTREAM_BASE_URL" \
UPSTREAM_API_KEY="$UPSTREAM_API_KEY" \
UPSTREAM_MODEL="$UPSTREAM_MODEL" \
LISTEN_PORT="$LISTEN_PORT" \
TOOLS_BASE_DIR="$TOOLS_BASE_DIR" \
CONFIG_PATH="$CONFIG_PATH" \
python3 -c '
import json
import os
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
data = json.loads(path.read_text(encoding="utf-8"))
data["listen_port"] = int(os.environ["LISTEN_PORT"])
data["tools_base_dir"] = os.environ["TOOLS_BASE_DIR"]
routing = data.setdefault("routing", data.pop("qwen", {}))
routing["base_url"] = os.environ["ROUTING_BASE_URL"]
routing["model"] = os.environ["ROUTING_MODEL"]
routing["api_key"] = os.environ["ROUTING_API_KEY"]
data["upstream"]["base_url"] = os.environ["UPSTREAM_BASE_URL"]
data["upstream"]["api_key"] = os.environ["UPSTREAM_API_KEY"]
data["upstream"]["model"] = os.environ["UPSTREAM_MODEL"]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'

mkdir -p "$(dirname "$OPENCLAW_CONFIG")"
if [ ! -f "$OPENCLAW_CONFIG" ]; then
  printf '{}\n' > "$OPENCLAW_CONFIG"
fi

BACKUP_PATH="${OPENCLAW_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
cp "$OPENCLAW_CONFIG" "$BACKUP_PATH"

ROUTER_BASE_URL="http://127.0.0.1:${LISTEN_PORT}/v1"
OPENCLAW_CONFIG="$OPENCLAW_CONFIG" \
ROUTER_BASE_URL="$ROUTER_BASE_URL" \
python3 -c '
import json
import os
from pathlib import Path

path = Path(os.environ["OPENCLAW_CONFIG"])
raw = path.read_text(encoding="utf-8").strip() or "{}"
data = json.loads(raw)

models = data.setdefault("models", {})
providers = models.setdefault("providers", {})
providers["function_router"] = {
    "baseUrl": os.environ["ROUTER_BASE_URL"],
    "apiKey": "any",
    "api": "openai-completions",
    "models": [{"id": "function-router", "name": "Function Router"}],
}

agents = data.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
model = defaults.setdefault("model", {})
model["primary"] = "function_router/function-router"

plugins = data.setdefault("plugins", {})
allow = plugins.setdefault("allow", [])
if "session-bridge" not in allow:
    allow.append("session-bridge")
entries = plugins.setdefault("entries", {})
entries["session-bridge"] = {"enabled": True}

path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
'

echo
echo "Install complete."
echo "安装完成。"
echo "Config: $CONFIG_PATH"
echo "配置: $CONFIG_PATH"
echo "Functions: $FUNCTIONS_PATH"
echo "函数定义: $FUNCTIONS_PATH"
echo "Scripts: $SCRIPTS_DIR"
echo "脚本目录: $SCRIPTS_DIR"
echo "Logs: $LOGS_DIR"
echo "日志目录: $LOGS_DIR"
echo "Tools base dir: $TOOLS_BASE_DIR"
echo "工具根目录: $TOOLS_BASE_DIR"
echo "OpenClaw config: $OPENCLAW_CONFIG"
echo "OpenClaw 配置: $OPENCLAW_CONFIG"
echo "OpenClaw backup: $BACKUP_PATH"
echo "OpenClaw 备份: $BACKUP_PATH"
echo "Primary model: function_router/function-router"
echo "主模型: function_router/function-router"
echo "Router base_url: $ROUTER_BASE_URL"
echo "Router 地址: $ROUTER_BASE_URL"
echo "Session bridge plugin: $PLUGIN_DST"
echo "Session bridge 插件: $PLUGIN_DST"
