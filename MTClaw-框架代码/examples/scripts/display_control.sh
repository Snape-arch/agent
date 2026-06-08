#!/bin/bash
set -euo pipefail

# Display control wrapper - calls real Python tool
TOOL_PATH="${FR_TOOLS_BASE_DIR}/display-control/scripts/display-control.py"

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
POSITION=$(echo "$INPUT" | jq -r '.position | select(. != null)')
DISPLAY_NAME=$(echo "$INPUT" | jq -r '.display_name | select(. != null)')
WIDTH=$(echo "$INPUT" | jq -r '.width | select(. != null)')
HEIGHT=$(echo "$INPUT" | jq -r '.height | select(. != null)')
RATE=$(echo "$INPUT" | jq -r '.rate | select(. != null)')
VALUE=$(echo "$INPUT" | jq -r '.value | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Build command arguments array based on category + action
ARGS=()

case "$CATEGORY" in
    theme)
        case "$ACTION" in
            dark)   ARGS=("dark") ;;
            light)  ARGS=("light") ;;
            status) ARGS=("theme" "status") ;;
            *)      error_exit "invalid action for theme: $ACTION (expected dark/light/status)" ;;
        esac
        ;;
    display)
        case "$ACTION" in
            list)
                ARGS=("display" "list")
                ;;
            status)
                ARGS=("display" "status")
                ;;
            extend)
                [ -z "$POSITION" ] && error_exit "position required for extend (left|right|above|below)"
                [[ ! $POSITION =~ ^(left|right|above|below)$ ]] && error_exit "invalid position: $POSITION"
                ARGS=("display" "extend" "$POSITION")
                ;;
            mirror)
                ARGS=("display" "mirror")
                ;;
            internal-only)
                ARGS=("display" "internal-only")
                ;;
            external-only)
                ARGS=("display" "external-only")
                ;;
            set-primary)
                [ -z "$DISPLAY_NAME" ] && error_exit "display_name required for set-primary"
                ARGS=("display" "set-primary" "$DISPLAY_NAME")
                ;;
            mouse-arrange)
                ARGS=("display" "mouse-arrange")
                ;;
            *)
                error_exit "invalid action for display: $ACTION"
                ;;
        esac
        ;;
    resolution)
        [ "$ACTION" != "set" ] && error_exit "resolution only supports action=set"
        [ -z "$WIDTH" ] || [ -z "$HEIGHT" ] && error_exit "width and height required for resolution set"
        [[ ! $WIDTH =~ ^[0-9]+$ ]] && error_exit "width must be a number"
        [[ ! $HEIGHT =~ ^[0-9]+$ ]] && error_exit "height must be a number"
        ARGS=("resolution" "$WIDTH" "$HEIGHT")
        ;;
    refresh-rate)
        [ "$ACTION" != "set" ] && error_exit "refresh-rate only supports action=set"
        [ -z "$RATE" ] && error_exit "rate required for refresh-rate set"
        [[ ! $RATE =~ ^[0-9]+$ ]] && error_exit "rate must be a number"
        ARGS=("refresh-rate" "$RATE")
        ;;
    brightness)
        [ "$ACTION" != "set" ] && error_exit "brightness only supports action=set"
        [ -z "$VALUE" ] && error_exit "value required for brightness set"
        [[ ! $VALUE =~ ^[0-9]+$ ]] && error_exit "value must be a number"
        ARGS=("brightness" "$VALUE")
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
