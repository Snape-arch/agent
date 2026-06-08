#!/bin/bash
set -euo pipefail

# Power control wrapper - calls real Python tool
TOOL_PATH="${FR_TOOLS_BASE_DIR}/power-control/scripts/power-control.py"

# Error output helper - ensures all errors are JSON
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
SECONDS_VAL=$(echo "$INPUT" | jq -r '.seconds | select(. != null)')
TIME=$(echo "$INPUT" | jq -r '.time | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Build command arguments array (safe from injection)
ARGS=()

case "$CATEGORY" in
    status)
        case "$ACTION" in
            status)  ARGS=("status") ;;
            battery) ARGS=("battery") ;;
            *)       error_exit "invalid action for status: $ACTION (expected status/battery)" ;;
        esac
        ;;
    screen)
        case "$ACTION" in
            off)  ARGS=("screen" "off") ;;
            on)   ARGS=("screen" "on") ;;
            lock) ARGS=("lock") ;;
            *)    error_exit "invalid action for screen: $ACTION (expected off/on/lock)" ;;
        esac
        ;;
    power)
        case "$ACTION" in
            shutdown|reboot|suspend|logout) ARGS=("$ACTION") ;;
            *) error_exit "invalid action for power: $ACTION (expected shutdown/reboot/suspend/logout)" ;;
        esac
        ;;
    delay)
        case "$ACTION" in
            delay-shutdown|delay-reboot|delay-suspend|delay-screen-off)
                [ -z "$SECONDS_VAL" ] && error_exit "seconds required for $ACTION"
                [[ ! $SECONDS_VAL =~ ^[0-9]+$ ]] && error_exit "seconds must be a positive integer"
                [ "$SECONDS_VAL" -le 0 ] && error_exit "seconds must be > 0"
                ARGS=("$ACTION" "$SECONDS_VAL")
                ;;
            *) error_exit "invalid action for delay: $ACTION (expected delay-shutdown/delay-reboot/delay-suspend/delay-screen-off)" ;;
        esac
        ;;
    schedule)
        case "$ACTION" in
            schedule-shutdown|schedule-reboot)
                [ -z "$TIME" ] && error_exit "time required for $ACTION"
                ARGS=("$ACTION" "$TIME")
                ;;
            schedule-list)
                ARGS=("schedule-list")
                ;;
            schedule-cancel)
                ARGS=("schedule-cancel")
                ;;
            *) error_exit "invalid action for schedule: $ACTION (expected schedule-shutdown/schedule-reboot/schedule-list/schedule-cancel)" ;;
        esac
        ;;
    *)
        error_exit "unknown category: $CATEGORY"
        ;;
esac

# Execute Python tool safely with arguments array
if OUTPUT=$(python3 "$TOOL_PATH" "${ARGS[@]}" 2>&1); then
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')

    # Check for failure markers in output
    if echo "$CLEAN" | grep -q '✗\|失败\|无法'; then
        DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|无法' | head -1 | xargs)
        echo "{\"error\":\"operation failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"detail\":\"$DETAIL\"}"
        exit 1
    fi

    # Always include tool_output; status/battery get extra parsed fields
    TOOL_OUT=$(echo "$CLEAN" | jq -Rs .)
    case "$ACTION" in
        status)
            UPTIME=$(echo "$CLEAN" | grep "运行时间" | sed 's/.*运行时间.//' | xargs || echo "unknown")
            echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"uptime\":\"$UPTIME\",\"tool_output\":$TOOL_OUT}"
            ;;
        battery)
            if echo "$CLEAN" | grep -q "电量"; then
                CAPACITY=$(echo "$CLEAN" | grep "电量" | sed 's/.*电量.//' | xargs || echo "unknown")
                STATE=$(echo "$CLEAN" | grep "状态" | sed 's/.*状态.//' | xargs || echo "unknown")
                echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"capacity\":\"$CAPACITY\",\"state\":\"$STATE\",\"tool_output\":$TOOL_OUT}"
            else
                echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
            fi
            ;;
        *)
            echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
            ;;
    esac
else
    EXIT_CODE=$?
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')
    DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|error' | head -1 | xargs)
    echo "{\"error\":\"action failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"exit_code\":$EXIT_CODE,\"detail\":\"${DETAIL:-unknown error}\"}"
    exit 1
fi
