#!/bin/bash
set -euo pipefail

# WiFi/Bluetooth control wrapper - calls real Python tool
TOOL_PATH="${FR_TOOLS_BASE_DIR}/wifi-bluetooth-control/scripts/wifi-bluetooth.py"

# Error output helper
error_exit() {
    echo "{\"error\":\"$1\"}"
    exit 1
}

# Validate environment
[ -z "$FR_TOOLS_BASE_DIR" ] && error_exit "FR_TOOLS_BASE_DIR not set — configure tools_base_dir in config.json"
[ ! -f "$TOOL_PATH" ] && error_exit "tool not found: $TOOL_PATH"

# Read and parse input JSON
INPUT=$(cat)
CATEGORY=$(echo "$INPUT" | jq -r '.category | select(. != null)')
ACTION=$(echo "$INPUT" | jq -r '.action | select(. != null)')
SSID=$(echo "$INPUT" | jq -r '.ssid | select(. != null)')
PASSWORD=$(echo "$INPUT" | jq -r '.password | select(. != null)')
NAME_OR_MAC=$(echo "$INPUT" | jq -r '.name_or_mac | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Validate category value
case "$CATEGORY" in
    wifi|bluetooth) ;;
    *) error_exit "invalid category: $CATEGORY (must be wifi or bluetooth)" ;;
esac

# Build command arguments array based on actual tool interface
ARGS=("$CATEGORY")

case "$ACTION" in
    status|scan|on|off)
        ARGS+=("$ACTION")
        ;;
    connect)
        if [ "$CATEGORY" = "wifi" ]; then
            [ -z "$SSID" ] && error_exit "ssid required for wifi connect"
            ARGS+=("connect")
            ARGS+=(--ssid "$SSID")
            if [ -n "$PASSWORD" ]; then
                ARGS+=(--password "$PASSWORD")
            fi
        else  # bluetooth
            [ -z "$NAME_OR_MAC" ] && error_exit "name_or_mac required for bluetooth connect"
            ARGS+=("connect")
            ARGS+=(--name "$NAME_OR_MAC")
        fi
        ;;
    disconnect)
        if [ "$CATEGORY" = "wifi" ]; then
            ARGS+=("disconnect")
        else  # bluetooth
            ARGS+=("disconnect")
            if [ -n "$NAME_OR_MAC" ]; then
                ARGS+=("$NAME_OR_MAC")
            fi
        fi
        ;;
    pair)
        [ "$CATEGORY" = "wifi" ] && error_exit "pair not applicable for wifi"
        [ -z "$NAME_OR_MAC" ] && error_exit "name_or_mac required for pairing"
        ARGS+=("pair")
        ARGS+=(--name "$NAME_OR_MAC")
        ;;
    *)
        error_exit "unknown action: $ACTION"
        ;;
esac

# Execute Python tool safely
if OUTPUT=$(python3 "$TOOL_PATH" "${ARGS[@]}" 2>&1); then
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')

    # Check for failure markers
    if echo "$CLEAN" | grep -q '✗\|失败\|无法'; then
        DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|无法' | head -1 | xargs)
        echo "{\"error\":\"operation failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"detail\":\"$DETAIL\"}"
        exit 1
    fi

    # Always include tool_output for all actions
    TOOL_OUT=$(echo "$CLEAN" | jq -Rs .)
    echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
else
    EXIT_CODE=$?
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')
    DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|error' | head -1 | xargs)
    echo "{\"error\":\"action failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"exit_code\":$EXIT_CODE,\"detail\":\"${DETAIL:-unknown error}\"}"
    exit 1
fi
