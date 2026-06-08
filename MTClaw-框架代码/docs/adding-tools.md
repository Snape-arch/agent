# Adding New Tools

This guide walks through adding a new tool to Function Router, from defining the function schema to writing and testing the wrapper script.

## Step 1: Define the Function

Append one JSON object to `~/.function-router/functions.jsonl`. Each line is a standalone JSON object in [OpenAI function calling format](https://platform.openai.com/docs/guides/function-calling).

Example — adding a `timer_control` tool:

```json
{"name":"timer_control","description":"Set and manage timers and alarms.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["set","cancel","list"],"description":"Operation: set=create timer, cancel=cancel timer, list=show active timers"},"seconds":{"type":"integer","description":"Duration in seconds, required for set"},"label":{"type":"string","description":"Optional label for the timer"}},"required":["action"]}}
```

Tips:
- `name` must match the script filename exactly (without `.sh`).
- Keep `description` concise but include enough detail for the routing model to match user intent.
- Use `enum` for action parameters — this helps the routing model pick the correct value.
- Mark truly required fields in `required`, leave optional fields out.

## Step 2: Create the Wrapper Script

Create `~/.function-router/scripts/<name>.sh`. The script receives JSON on **stdin** and must output JSON on **stdout**.

### Template

```bash
#!/bin/bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────
TOOL_PATH="/path/to/your/tool.py"
PYTHON3="python3"

# ── Error helper ───────────────────────────────────────────
error_exit() {
    echo "{\"error\":\"$1\"}"
    exit 1
}

# ── Read & validate input ─────────────────────────────────
INPUT=$(cat)
CATEGORY=$(echo "$INPUT" | jq -r '.category | select(. != null)')
ACTION=$(echo "$INPUT" | jq -r '.action | select(. != null)')
# Add more parameters as needed:
# VALUE=$(echo "$INPUT" | jq -r '.value | select(. != null)')

[ -z "$CATEGORY" ] && error_exit "missing category parameter"
[ -z "$ACTION" ] && error_exit "missing action parameter"
[ ! -f "$TOOL_PATH" ] && error_exit "tool not found: $TOOL_PATH"

# Validate category enum
case "$CATEGORY" in
    option_a|option_b) ;;
    *) error_exit "unknown category: $CATEGORY" ;;
esac

# Validate action enum per category
# case "$CATEGORY" in
#     option_a) case "$ACTION" in status|set) ;; *) error_exit "..." ;; esac ;;
# esac

# Validate conditional parameters
# if [ "$ACTION" = "set" ]; then
#     [ -z "$VALUE" ] && error_exit "value required for set"
#     [[ ! $VALUE =~ ^[0-9]+$ ]] && error_exit "value must be a positive integer"
# fi

# ── Build arguments ───────────────────────────────────────
ARGS=("$CATEGORY" "$ACTION")
# if [ -n "$VALUE" ]; then
#     ARGS+=("$VALUE")
# fi

# ── Execute ───────────────────────────────────────────────
if OUTPUT=$("$PYTHON3" "$TOOL_PATH" "${ARGS[@]}" 2>&1); then
    # Strip ANSI color codes from tool output
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')

    # Check for failure markers (tools may return exit 0 on failure)
    if echo "$CLEAN" | grep -q '✗\|失败\|无法'; then
        DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|无法' | head -1 | xargs)
        echo "{\"error\":\"operation failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"detail\":\"$DETAIL\"}"
        exit 1
    fi

    # For query actions: include tool_output so downstream LLM can use the data
    case "$ACTION" in
        status|scan|list)
            TOOL_OUT=$(echo "$CLEAN" | jq -Rs .)
            echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"tool_output\":$TOOL_OUT}"
            ;;
        *)
            echo "{\"result\":\"ok\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"status\":\"success\"}"
            ;;
    esac
else
    EXIT_CODE=$?
    CLEAN=$(echo "$OUTPUT" | sed 's/\x1b\[[0-9;]*m//g')
    DETAIL=$(echo "$CLEAN" | grep '✗\|失败\|error' | head -1 | xargs)
    echo "{\"error\":\"action failed\",\"category\":\"$CATEGORY\",\"action\":\"$ACTION\",\"exit_code\":$EXIT_CODE,\"detail\":\"${DETAIL:-unknown error}\"}"
    exit 1
fi
```

### Key Rules

| Rule | Why |
|------|-----|
| Use `jq -r '.field \| select(. != null)'` | `jq -r '.field'` returns literal `"null"` when field is missing — `select` filters it to empty |
| Use bash arrays for args: `ARGS=()` + `"${ARGS[@]}"` | Prevents command injection and whitespace splitting |
| All output paths must produce valid JSON | Function Router parses stdout as JSON; plain text breaks the chain |
| Check output content, not just exit code | Many Python tools return exit 0 even on failure |
| Strip ANSI codes: `sed 's/\x1b\[[0-9;]*m//g'` | Python tools often output colored text |
| Include `tool_output` for query actions (status/scan/list) | Without it the downstream LLM only sees "success" and cannot give a meaningful answer |
| Use `category` + `action` two-level structure | Reduces routing model decision space; the model picks a small category first, then a short action list |

## Step 3: Make Executable and Restart

```bash
chmod +x ~/.function-router/scripts/timer_control.sh
# Restart to pick up new function definitions
./restart_all.sh
# Or just kill and restart:
pkill -f "function_router/server.py"
nohup python3 -m function_router.server > /tmp/function-router.log 2>&1 &
```

Verify:

```bash
curl -s http://127.0.0.1:18790/health | jq .
# tools_loaded should increase by 1
```

## Step 4: Test

### Unit test (direct script call)

```bash
# Normal path
echo '{"action":"list"}' | bash ~/.function-router/scripts/timer_control.sh
# Expected: {"result":"ok","action":"list","status":"success"}

# Missing required param
echo '{}' | bash ~/.function-router/scripts/timer_control.sh
# Expected: exit 1, {"error":"missing action parameter"}

# Invalid action
echo '{"action":"foo"}' | bash ~/.function-router/scripts/timer_control.sh
# Expected: exit 1, {"error":"unknown action: foo"}
```

### Integration test (through Function Router)

```bash
curl -s -X POST http://127.0.0.1:18790/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"function-router","messages":[{"role":"user","content":"帮我设置一个5分钟的计时器"}],"stream":false}'
```

Check Function Router logs:
```bash
strings /tmp/function-router.log | grep '"route"' | tail -1
# function_name should be "timer_control", status should be "tool_result_to_upstream"
```

### End-to-end test (through OpenClaw Gateway)

```bash
curl -s -X POST http://127.0.0.1:18789/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-gateway-token>" \
  -d '{"model":"function_router/function-router","messages":[{"role":"user","content":"帮我设置一个5分钟的计时器"}],"stream":false}' \
  | jq -r '.choices[0].message.content'
```

### Verification (confirm real effect)

After the tool claims success, verify with a system command:
```bash
# Example: after setting volume to 50%
pactl get-sink-volume @DEFAULT_SINK@
# Should show 50%, not the old value
```

## Checklist

Before deploying a new tool:

- [ ] Function definition added to `functions.jsonl` (valid JSON, one line)
- [ ] `name` in JSON matches script filename (without `.sh`)
- [ ] Script uses `jq | select(. != null)` for all parameter extraction
- [ ] All required params have `[ -z "$VAR" ]` checks
- [ ] Args built with bash arrays, expanded with `"${ARGS[@]}"`
- [ ] All success/failure branches output valid JSON
- [ ] ANSI codes stripped from tool output
- [ ] Output content checked for failure markers (`✗`, `失败`, `无法`)
- [ ] Query actions (status/scan/list) return `tool_output` field via `jq -Rs .`
- [ ] Mutation actions do not include `tool_output` (avoid unnecessary data)
- [ ] Script is executable (`chmod +x`)
- [ ] Unit tests pass: normal path + all error paths
- [ ] Integration test: Function Router log shows correct `function_name` and `status`
- [ ] End-to-end test: natural language → tool execution → response includes real data
- [ ] Real effect verified with system command
