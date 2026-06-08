#!/bin/bash
set -euo pipefail

# VLC control wrapper - calls real Python tool for media playback

# Error output helper
error_exit() {
    echo "{\"error\":\"$1\"}"
    exit 1
}

# Validate environment
[ -z "${FR_TOOLS_BASE_DIR:-}" ] && error_exit "FR_TOOLS_BASE_DIR not set — configure tools_base_dir in config.json"

TOOL_PATH="${FR_TOOLS_BASE_DIR}/vlc-control/scripts/vlc-control.py"
[ ! -f "$TOOL_PATH" ] && error_exit "tool not found: $TOOL_PATH"

load_desktop_session_env() {
    local shell_pid key value uid xauth_candidate

    shell_pid=$(pgrep -n gnome-shell || true)
    if [ -n "$shell_pid" ] && [ -r "/proc/$shell_pid/environ" ]; then
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
        done < <(tr '\0' '\n' < "/proc/$shell_pid/environ")
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
FILE=$(echo "$INPUT" | jq -r '.file | select(. != null)')
DIR=$(echo "$INPUT" | jq -r '.dir | select(. != null)')
RECURSIVE=$(echo "$INPUT" | jq -r '.recursive | select(. != null)')
FILES=$(echo "$INPUT" | jq -r '.files | select(. != null)')
INDEX=$(echo "$INPUT" | jq -r '.index | select(. != null)')
SECONDS=$(echo "$INPUT" | jq -r '.seconds | select(. != null)')
LEVEL=$(echo "$INPUT" | jq -r '.level | select(. != null)')
STEP=$(echo "$INPUT" | jq -r '.step | select(. != null)')
SPEED=$(echo "$INPUT" | jq -r '.speed | select(. != null)')

# Validate required parameters
[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"

# Validate category
case "$CATEGORY" in
    playback|playlist|seek|volume|rate|other) ;;
    *) error_exit "unknown category: $CATEGORY" ;;
esac

# Build command arguments based on category and action
ARGS=()

case "$CATEGORY" in
    playback)
        case "$ACTION" in
            start|play|pause|next|prev|status)
                ARGS+=("$ACTION")
                if [ "$ACTION" = "play" ] && [ -n "$FILE" ]; then
                    ARGS+=("$FILE")
                fi
                ;;
            *) error_exit "unknown action for playback: $ACTION" ;;
        esac
        ;;
    playlist)
        case "$ACTION" in
            list)
                ARGS+=("playlist")
                ;;
            clear)
                ARGS+=("playlist-clear")
                ;;
            add)
                if [ -n "$FILE" ]; then
                    ARGS+=("playlist-add" "$FILE")
                elif [ -n "$DIR" ]; then
                    ARGS+=("playlist-add-dir" "$DIR")
                    if [ "$RECURSIVE" = "true" ]; then
                        ARGS+=("--recursive")
                    fi
                else
                    error_exit "file or dir required for playlist add"
                fi
                ;;
            add-dir)
                [ -z "$DIR" ] && error_exit "dir required for add-dir"
                ARGS+=("playlist-add-dir" "$DIR")
                if [ "$RECURSIVE" = "true" ]; then
                    ARGS+=("--recursive")
                fi
                ;;
            add-multiple)
                ARGS+=("playlist-add-multiple")
                if [ -n "$FILES" ]; then
                    # Parse JSON array and add each file
                    while IFS= read -r f; do
                        [ -n "$f" ] && ARGS+=("$f")
                    done < <(echo "$FILES" | jq -r '.[]')
                fi
                ;;
            remove)
                [ -z "$INDEX" ] && error_exit "index required for playlist remove"
                ARGS+=("playlist-remove" "$INDEX")
                ;;
            play)
                [ -z "$INDEX" ] && error_exit "index required for playlist play"
                ARGS+=("playlist-play" "$INDEX")
                ;;
            *) error_exit "unknown action for playlist: $ACTION" ;;
        esac
        ;;
    seek)
        case "$ACTION" in
            seek)
                [ -z "$SECONDS" ] && error_exit "seconds required for seek"
                ARGS+=("seek" "$SECONDS")
                ;;
            forward|rewind)
                ARGS+=("$ACTION")
                [ -n "$SECONDS" ] && ARGS+=("$SECONDS")
                ;;
            *) error_exit "unknown action for seek: $ACTION" ;;
        esac
        ;;
    volume)
        case "$ACTION" in
            set)
                [ -z "$LEVEL" ] && error_exit "level required for volume set"
                ARGS+=("volume" "$LEVEL")
                ;;
            up|down)
                ARGS+=("volume-$ACTION")
                [ -n "$STEP" ] && ARGS+=("$STEP")
                ;;
            max|min)
                ARGS+=("volume-$ACTION")
                ;;
            *) error_exit "unknown action for volume: $ACTION" ;;
        esac
        ;;
    rate)
        [ "$ACTION" != "rate" ] && error_exit "rate category only supports action=rate"
        [ -z "$SPEED" ] && error_exit "speed required for rate"
        ARGS+=("rate" "$SPEED")
        ;;
    other)
        case "$ACTION" in
            fullscreen-on|fullscreen-off|quit)
                ARGS+=("$ACTION")
                ;;
            *) error_exit "unknown action for other: $ACTION" ;;
        esac
        ;;
esac

# Execute
if OUTPUT=$(python3 "$TOOL_PATH" "${ARGS[@]}" 2>&1); then
    # Strip ANSI codes
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')

    # Check for failure markers in output
    if echo "$CLEAN" | grep -q '✗\|失败\|无法\|不存在\|未找到'; then
        DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|无法\|不存在\|未找到' | head -1 | xargs)
        echo "{\"error\":\"operation failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"detail\":\"$DETAIL\"}"
        exit 1
    fi

    # Include tool_output for LLM response
    TOOL_OUT=$(echo "$CLEAN" | jq -Rs .)
    echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
else
    EXIT_CODE=$?
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')
    DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|error\|Error' | head -1 | xargs)
    echo "{\"error\":\"action failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"exit_code\":$EXIT_CODE,\"detail\":\"${DETAIL:-unknown error}\"}"
    exit 1
fi
