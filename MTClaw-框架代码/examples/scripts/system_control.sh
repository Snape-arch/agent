#!/bin/bash
set -euo pipefail

# System control wrapper - calls real Python tool for volume/brightness
TOOL_PATH="${FR_TOOLS_BASE_DIR}/system-control/scripts/system-control.py"

# Error output helper
error_exit() {
    echo "{\"error\":\"$1\"}"
    exit 1
}

# Validate environment
[ -z "${FR_TOOLS_BASE_DIR:-}" ] && error_exit "FR_TOOLS_BASE_DIR not set — configure tools_base_dir in config.json"
[ ! -f "$TOOL_PATH" ] && error_exit "tool not found: $TOOL_PATH"

load_desktop_session_env() {
    local shell_pid environ_file key value uid xauth_candidate

    if [ -n "${GNOME_SHELL_PID_FILE:-}" ] && [ -r "${GNOME_SHELL_PID_FILE}" ]; then
        shell_pid=$(tr -d '\n' < "${GNOME_SHELL_PID_FILE}")
    else
        shell_pid=$(pgrep -n gnome-shell || true)
    fi

    if [ -n "${GNOME_ENV_FILE:-}" ] && [ -r "${GNOME_ENV_FILE}" ]; then
        environ_file="${GNOME_ENV_FILE}"
    elif [ -n "$shell_pid" ] && [ -r "/proc/$shell_pid/environ" ]; then
        environ_file="/proc/$shell_pid/environ"
    else
        environ_file=""
    fi

    if [ -n "$environ_file" ]; then
        while IFS='=' read -r key value; do
            case "$key" in
                DISPLAY)
                    [ -z "${DISPLAY:-}" ] && export DISPLAY="$value"
                    ;;
                WAYLAND_DISPLAY)
                    [ -z "${WAYLAND_DISPLAY:-}" ] && export WAYLAND_DISPLAY="$value"
                    ;;
                XDG_RUNTIME_DIR)
                    [ -z "${XDG_RUNTIME_DIR:-}" ] && export XDG_RUNTIME_DIR="$value"
                    ;;
                DBUS_SESSION_BUS_ADDRESS)
                    [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && export DBUS_SESSION_BUS_ADDRESS="$value"
                    ;;
                XAUTHORITY)
                    [ -z "${XAUTHORITY:-}" ] && export XAUTHORITY="$value"
                    ;;
            esac
        done < <(tr '\0' '\n' < "$environ_file")
    fi

    uid=$(id -u)
    [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$uid" ] && export XDG_RUNTIME_DIR="/run/user/$uid"
    [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "${XDG_RUNTIME_DIR}/bus" ] && export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    [ -z "${DISPLAY:-}" ] && [ -n "$shell_pid" ] && export DISPLAY=":0"
    [ -z "${WAYLAND_DISPLAY:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "${XDG_RUNTIME_DIR}/wayland-0" ] && export WAYLAND_DISPLAY="wayland-0"

    if [ -z "${XAUTHORITY:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ]; then
        xauth_candidate=$(find "${XDG_RUNTIME_DIR}" -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit 2>/dev/null || true)
        [ -n "$xauth_candidate" ] && export XAUTHORITY="$xauth_candidate"
    fi
}

load_desktop_session_env

# Read and parse input JSON
INPUT=$(cat)
CATEGORY=$(echo "$INPUT" | jq -r '.category | select(. != null)')
ACTION=$(echo "$INPUT" | jq -r '.action | select(. != null)')
VALUE=$(echo "$INPUT" | jq -r '.value | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Validate category
case "$CATEGORY" in
    volume|brightness) ;;
    *) error_exit "unknown category: $CATEGORY" ;;
esac

# Validate action
case "$ACTION" in
    status|up|down|set|mute|unmute|max|min) ;;
    *) error_exit "unknown action: $ACTION" ;;
esac

# Validate value for set action
if [ "$ACTION" = "set" ]; then
    [ -z "$VALUE" ] && error_exit "value required for set action"
    [[ ! $VALUE =~ ^[0-9]+$ ]] && error_exit "value must be a positive integer"
    [ "$VALUE" -gt 100 ] && error_exit "value too large (max 100)"
fi

# Build command arguments
ARGS=("$CATEGORY" "$ACTION")
if [ "$ACTION" = "set" ] && [ -n "$VALUE" ]; then
    ARGS+=("$VALUE")
fi

# Execute
if OUTPUT=$(python3 "$TOOL_PATH" "${ARGS[@]}" 2>&1); then
    # Strip ANSI codes
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')

    # Check for failure markers in output
    if echo "$CLEAN" | grep -q '✗\|失败\|无法'; then
        DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|无法' | head -1 | xargs)
        echo "{\"error\":\"operation failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"detail\":\"$DETAIL\"}"
        exit 1
    fi

    # Always include tool_output; status actions get extra parsed fields
    TOOL_OUT=$(echo "$CLEAN" | jq -Rs .)
    if [ "$ACTION" = "status" ]; then
        case "$CATEGORY" in
            volume)
                CURRENT=$(echo "$CLEAN" | grep -o '[0-9]*%' | head -1 | tr -d '%')
                MUTED=$(echo "$CLEAN" | grep -qi '静音.*是\|muted.*yes\|mute: yes' && echo "true" || echo "false")
                echo "{\"result\":\"ok\",\"category\":\"volume\",\"action\":\"status\",\"current_value\":${CURRENT:-0},\"muted\":$MUTED,\"tool_output\":$TOOL_OUT}"
                ;;
            brightness)
                CURRENT=$(echo "$CLEAN" | grep -o '[0-9]*%' | head -1 | tr -d '%')
                echo "{\"result\":\"ok\",\"category\":\"brightness\",\"action\":\"status\",\"current_value\":${CURRENT:-0},\"tool_output\":$TOOL_OUT}"
                ;;
        esac
    else
        echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
    fi
else
    EXIT_CODE=$?
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')
    DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|error' | head -1 | xargs)
    echo "{\"error\":\"action failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"exit_code\":$EXIT_CODE,\"detail\":\"${DETAIL:-unknown error}\"}"
    exit 1
fi
