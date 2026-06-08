#!/bin/bash
set -euo pipefail

# System settings wrapper - calls real Python tool
TOOL_PATH="${FR_TOOLS_BASE_DIR}/system-settings/scripts/system-settings.py"

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

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Validate category
case "$CATEGORY" in
    location|sharing) ;;
    *) error_exit "unknown category: $CATEGORY (expected location/sharing)" ;;
esac

# Validate action per category
case "$CATEGORY" in
    location)
        case "$ACTION" in
            on|off|status) ;;
            *) error_exit "invalid action for location: $ACTION (expected on/off/status)" ;;
        esac
        ;;
    sharing)
        case "$ACTION" in
            status|ui) ;;
            *) error_exit "invalid action for sharing: $ACTION (expected status/ui)" ;;
        esac
        ;;
esac

# Build command arguments: system-settings.py <category> <action>
ARGS=("$CATEGORY" "$ACTION")

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
