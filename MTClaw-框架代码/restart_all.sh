#!/bin/bash

# Function Router + OpenClaw 全服务重启脚本
# 启动顺序：Function Router → OpenClaw Gateway
# 停止顺序：OpenClaw Gateway → Function Router
#
# 用法:
#   ./restart_all.sh

set -e

# ── 用户配置区（新机器只改这里） ──
PYTHON="${PYTHON:-python3}"                           # Python 解释器，默认用 PATH 里的
FR_REPO="${FR_REPO:-$(cd "$(dirname "$0")" && pwd)}"  # FR 仓库根目录（默认为脚本所在目录）
# ── 用户配置区结束 ──

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FR_MAIN="$FR_REPO/function_router/server.py"
FR_CONFIG="$HOME/.function-router/config.json"
FR_LOG="/tmp/function-router.log"
FR_PID_FILE="/tmp/function-router.pid"
GW_LOG="/tmp/openclaw-gateway.log"

echo -e "${GREEN}=== 全服务重启脚本 (Function Router + OpenClaw) ===${NC}\n"

echo "清空垃圾session"
openclaw sessions cleanup --enforce

# ── 1. 停止 OpenClaw Gateway ──
echo -e "\n${YELLOW}[1/4] 停止 OpenClaw Gateway...${NC}"
GATEWAY_PIDS=$(pgrep -f "openclaw-gateway" || true)
if [ -n "$GATEWAY_PIDS" ]; then
    echo "找到 Gateway 进程: $GATEWAY_PIDS"
    kill $GATEWAY_PIDS
    sleep 2
    if pgrep -f "openclaw-gateway" > /dev/null; then
        pkill -9 -f "openclaw-gateway" || true
    fi
    echo "✓ OpenClaw Gateway 已停止"
else
    echo "✓ OpenClaw Gateway 未运行"
fi

# ── 2. 停止 Function Router ──
echo -e "\n${YELLOW}[2/4] 停止 Function Router...${NC}"
FR_STOPPED=false
if [ -f "$FR_PID_FILE" ]; then
    OLD_PID=$(cat "$FR_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "找到 Function Router PID 文件进程: $OLD_PID"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        FR_STOPPED=true
    else
        echo "✓ PID 文件中的进程 $OLD_PID 已不存在"
    fi
    rm -f "$FR_PID_FILE"
fi

FR_PIDS=$(lsof -ti:18790 || true)
if [ -n "$FR_PIDS" ]; then
    echo "找到占用 18790 端口的 Function Router 进程: $FR_PIDS"
    kill $FR_PIDS 2>/dev/null || true
    sleep 2
    REMAINING_FR_PIDS=$(lsof -ti:18790 || true)
    if [ -n "$REMAINING_FR_PIDS" ]; then
        kill -9 $REMAINING_FR_PIDS 2>/dev/null || true
    fi
    FR_STOPPED=true
fi

for i in {1..10}; do
    if ! lsof -ti:18790 > /dev/null 2>&1; then
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}✗ Function Router 端口 18790 仍被占用，停止失败${NC}"
        lsof -iTCP:18790 -sTCP:LISTEN -Pn || true
        exit 1
    fi
    sleep 1
done

if $FR_STOPPED; then
    echo "✓ Function Router 已停止"
else
    echo "✓ Function Router 未运行"
fi

echo -e "\n${GREEN}--- 所有服务已停止，开始启动 ---${NC}\n"

# ── 3. 启动 Function Router ──
echo -e "${YELLOW}[3/4] 启动 Function Router...${NC}"
if [ ! -f "$FR_MAIN" ] || [ ! -f "$FR_CONFIG" ]; then
    echo -e "${RED}✗ Function Router 文件缺失 (server.py 或 config.json)${NC}"
    exit 1
fi

# 检查路由模型接口
ROUTING_CHECK=$($PYTHON - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

config_path = os.path.expanduser("~/.function-router/config.json")
try:
    data = json.load(open(config_path, encoding="utf-8"))
    cfg = data.get("routing", data.get("qwen"))
    if cfg is None:
        raise KeyError("routing")
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "stream": False,
        "temperature": 0,
        "max_tokens": 8,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + cfg.get("api_key", ""),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    response_model = data.get("model") or cfg["model"]
    print(f"OK\t{cfg['base_url']}\t{cfg['model']}\t{response_model}")
except Exception as exc:
    print(f"FAIL\t{type(exc).__name__}: {exc}")
    sys.exit(1)
PY
)
if [ $? -eq 0 ]; then
    ROUTING_URL=$(printf '%s' "$ROUTING_CHECK" | cut -f2)
    ROUTING_CONFIG_MODEL=$(printf '%s' "$ROUTING_CHECK" | cut -f3)
    ROUTING_RESPONSE_MODEL=$(printf '%s' "$ROUTING_CHECK" | cut -f4)
    echo "✓ 路由模型接口可达: 配置模型=$ROUTING_CONFIG_MODEL，返回模型=$ROUTING_RESPONSE_MODEL ($ROUTING_URL)"
else
    ROUTING_ERROR=$(printf '%s' "$ROUTING_CHECK" | cut -f2-)
    echo -e "${YELLOW}⚠ 路由模型接口不可达: $ROUTING_ERROR，Function Router 将以降级模式运行${NC}"
fi

# 注入图形会话环境变量，让 power-control 等脚本能正确操作屏幕
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

if lsof -ti:18790 > /dev/null 2>&1; then
    echo -e "${RED}✗ Function Router 启动前发现 18790 端口仍被占用${NC}"
    lsof -iTCP:18790 -sTCP:LISTEN -Pn || true
    exit 1
fi

nohup $PYTHON "$FR_MAIN" > "$FR_LOG" 2>&1 &
FR_PID=$!
echo "$FR_PID" > "$FR_PID_FILE"
echo "✓ Function Router 已启动 (PID: $FR_PID)"

for i in {1..10}; do
    if curl -s http://127.0.0.1:18790/health > /dev/null 2>&1; then
        TOOLS=$(curl -s http://127.0.0.1:18790/health | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['tools_loaded'])" 2>/dev/null || echo "?")
        echo "✓ Function Router 健康检查通过 (已加载 $TOOLS 个工具)"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}✗ Function Router 启动超时${NC}"
        tail -10 "$FR_LOG"
        exit 1
    fi
    sleep 1
done

# ── 4. 启动 OpenClaw Gateway ──
echo -e "\n${YELLOW}[4/4] 启动 OpenClaw Gateway...${NC}"
cd ~/.openclaw
nohup openclaw gateway > "$GW_LOG" 2>&1 &
GW_PID=$!
echo "✓ OpenClaw Gateway 已启动 (PID: $GW_PID)"

sleep 30
if pgrep -f "openclaw-gateway" > /dev/null || curl -s http://127.0.0.1:18789/health > /dev/null 2>&1; then
    echo "✓ Gateway 进程运行中"
else
    echo -e "${RED}✗ Gateway 启动失败${NC}"
    tail -10 "$GW_LOG"
    exit 1
fi

# ── 完成 ──
echo -e "\n${GREEN}=== 全部启动完成 ===${NC}"
echo -e "\n服务状态："
echo "  Function Router:    http://127.0.0.1:18790/health"
echo "  OpenClaw Gateway:   ws://0.0.0.0:18789"
echo -e "\n日志文件："
echo "  Function Router:  $FR_LOG"
echo "  OpenClaw Gateway: $GW_LOG"
echo -e "\n管理命令："
echo "  查看全部进程: ps aux | grep -E '(function-router|openclaw-gateway)' | grep -v grep"
echo "  停止全部服务: kill \$(cat $FR_PID_FILE); pkill -f openclaw-gateway"
