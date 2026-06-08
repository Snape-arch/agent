#!/usr/bin/env bash
#
# Patch OpenClaw dist bundle to inject `x-openclaw-session-key` header on every
# provider stream request.
#
# Why this exists:
#   OpenClaw stores `chat.send.params.sessionKey` (e.g. `agent:main:batch-test-xxx`)
#   internally, but the plugin hooks `wrapStreamFn` / `resolveTransportTurnState`
#   only receive the runtime `sessionId` (a UUID). To let Function Router bucket
#   its `/v1/tool_history`, `_QWEN_SAVED_CONTEXTS`, and pending-upstream state
#   under the real AutoOpenClaw sessionKey, we wrap `activeSession.agent.streamFn`
#   at the core layer and emit `x-openclaw-session-key: <params.sessionKey>`.
#
# Idempotent: checks for the patch marker before applying. Re-running after an
# upgrade should only be needed when the pi-embedded-runner bundle hash changes.
#
# Usage:
#   bash patch-openclaw-session-header.sh              # apply
#   bash patch-openclaw-session-header.sh --revert     # restore .bak
#   bash patch-openclaw-session-header.sh --verify     # just check marker
set -euo pipefail

DIST_DIR=${OPENCLAW_DIST_DIR:-/usr/local/nodejs/lib/node_modules/openclaw/dist}
MARKER='SESSION_KEY_HEADER_PATCH'
ANCHOR='applyExtraParamsToAgent(activeSession.agent'

mode=${1:-apply}

locate_bundle() {
    local candidate
    for candidate in "$DIST_DIR"/pi-embedded-runner-*.js; do
        [[ -f "$candidate" ]] || continue
        if grep -q "$ANCHOR" "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    echo "error: could not find pi-embedded-runner bundle with anchor '$ANCHOR' under $DIST_DIR" >&2
    return 1
}

BUNDLE=$(locate_bundle)
BACKUP="${BUNDLE}.bak"

case "$mode" in
    --verify|verify)
        if grep -q "$MARKER" "$BUNDLE"; then
            echo "OK: patch present in $BUNDLE"
            exit 0
        fi
        echo "MISSING: patch not applied to $BUNDLE"
        exit 1
        ;;
    --revert|revert)
        if [[ ! -f "$BACKUP" ]]; then
            echo "error: backup $BACKUP does not exist; cannot revert" >&2
            exit 2
        fi
        cp "$BACKUP" "$BUNDLE"
        echo "reverted $BUNDLE from $BACKUP"
        echo "restart gateway: openclaw gateway restart"
        exit 0
        ;;
    apply|"")
        ;;
    *)
        echo "usage: $0 [apply|--verify|--revert]" >&2
        exit 2
        ;;
esac

if grep -q "$MARKER" "$BUNDLE"; then
    echo "noop: patch already applied in $BUNDLE"
    exit 0
fi

if [[ ! -f "$BACKUP" ]]; then
    cp "$BUNDLE" "$BACKUP"
    echo "created backup: $BACKUP"
fi

python3 - "$BUNDLE" "$MARKER" <<'PY'
import sys, re
from pathlib import Path

bundle = Path(sys.argv[1])
marker = sys.argv[2]
source = bundle.read_text(encoding="utf-8")

anchor_pattern = re.compile(
    r"(const \{ effectiveExtraParams \} = applyExtraParamsToAgent\(activeSession\.agent,[^;]*;\s*)",
    re.DOTALL,
)
match = anchor_pattern.search(source)
if not match:
    sys.stderr.write("error: anchor for applyExtraParamsToAgent not found\n")
    sys.exit(3)

patch = (
    "\n\t\t\t/* " + marker + ": inject AutoOpenClaw chat.send.params.sessionKey as x-openclaw-session-key */\n"
    "\t\t\t{\n"
    "\t\t\t\tconst __openclawSessionKey = typeof params.sessionKey === \"string\" ? params.sessionKey.trim() : \"\";\n"
    "\t\t\t\tif (__openclawSessionKey) {\n"
    "\t\t\t\t\tconst __innerStreamFnBeforeSessionKey = activeSession.agent.streamFn;\n"
    "\t\t\t\t\tactiveSession.agent.streamFn = (model, context, options) => __innerStreamFnBeforeSessionKey(model, context, {\n"
    "\t\t\t\t\t\t...options,\n"
    "\t\t\t\t\t\theaders: {\n"
    "\t\t\t\t\t\t\t...(options && options.headers ? options.headers : {}),\n"
    "\t\t\t\t\t\t\t\"x-openclaw-session-key\": __openclawSessionKey\n"
    "\t\t\t\t\t\t}\n"
    "\t\t\t\t\t});\n"
    "\t\t\t\t}\n"
    "\t\t\t}\n"
)

patched = anchor_pattern.sub(lambda m: m.group(1) + patch, source, count=1)
if marker not in patched:
    sys.stderr.write("error: patch insertion failed (marker missing after sub)\n")
    sys.exit(4)
bundle.write_text(patched, encoding="utf-8")
PY

echo "patched $BUNDLE"
if command -v node >/dev/null 2>&1; then
    if ! node --check "$BUNDLE"; then
        echo "error: node syntax check failed; reverting" >&2
        cp "$BACKUP" "$BUNDLE"
        exit 5
    fi
    echo "syntax OK"
fi

echo "restart gateway: openclaw gateway restart"
