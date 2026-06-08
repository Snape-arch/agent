#!/bin/bash
set -euo pipefail

export WALLPAPER_LIBRARY_PATH=/usr/share/backgrounds
# Wallpaper control wrapper - calls real Python tool
TOOL_PATH="${FR_TOOLS_BASE_DIR}/wallpaper-control/scripts/wallpaper-control.py"

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
PAGE=$(echo "$INPUT" | jq -r '.page | select(. != null)')
ID=$(echo "$INPUT" | jq -r '.id | select(. != null)')
WPATH=$(echo "$INPUT" | jq -r '.path | select(. != null)')
INTERVAL=$(echo "$INPUT" | jq -r '.interval | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Build command arguments array
# Python tool CLI: wallpaper-control.py <category> <action> [arg]
ARGS=()

case "$CATEGORY" in
    status)
        ARGS=("status")
        ;;
    library)
        case "$ACTION" in
            list)
                ARGS=("library" "list")
                if [ -n "$PAGE" ]; then
                    [[ ! $PAGE =~ ^[0-9]+$ ]] && error_exit "page must be a positive integer"
                    ARGS+=("$PAGE")
                fi
                ;;
            add)
                [ -z "$WPATH" ] && error_exit "path required for add"
                ARGS=("library" "add" "$WPATH")
                ;;
            remove)
                [ -z "$ID" ] && error_exit "id required for remove"
                [[ ! $ID =~ ^[0-9]+$ ]] && error_exit "id must be a positive integer"
                ARGS=("library" "remove" "$ID")
                ;;
            *)
                error_exit "invalid action for library: $ACTION (expected list/add/remove)"
                ;;
        esac
        ;;
    set)
        case "$ACTION" in
            next)
                ARGS=("set" "next")
                ;;
            prev)
                ARGS=("set" "prev")
                ;;
            random)
                ARGS=("set" "random")
                ;;
            path)
                [ -z "$WPATH" ] && error_exit "path required for set path"
                ARGS=("set" "path" "$WPATH")
                ;;
            id)
                [ -z "$ID" ] && error_exit "id required for set id"
                [[ ! $ID =~ ^[0-9]+$ ]] && error_exit "id must be a positive integer"
                ARGS=("set" "$ID")
                ;;
            *)
                error_exit "invalid action for set: $ACTION (expected next/prev/random/path/id)"
                ;;
        esac
        ;;
    nas)
        case "$ACTION" in
            list)
                ARGS=("nas" "list")
                ;;
            refresh)
                ARGS=("nas" "refresh")
                ;;
            set)
                [ -z "$ID" ] && error_exit "id required for nas set"
                [[ ! $ID =~ ^[0-9]+$ ]] && error_exit "id must be a positive integer"
                ARGS=("nas" "set" "$ID")
                ;;
            *)
                error_exit "invalid action for nas: $ACTION (expected list/refresh/set)"
                ;;
        esac
        ;;
    auto)
        case "$ACTION" in
            on)
                ARGS=("auto" "on")
                if [ -n "$INTERVAL" ]; then
                    [[ ! $INTERVAL =~ ^[0-9]+$ ]] && error_exit "interval must be a positive integer"
                    ARGS+=("$INTERVAL")
                fi
                ;;
            off)
                ARGS=("auto" "off")
                ;;
            status)
                ARGS=("auto" "status")
                ;;
            *)
                error_exit "invalid action for auto: $ACTION (expected on/off/status)"
                ;;
        esac
        ;;
    *)
        error_exit "unknown category: $CATEGORY"
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
