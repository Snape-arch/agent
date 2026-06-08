# Configuration Reference

`~/.function-router/config.json` drives runtime behavior.

## Core Settings

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `listen_host` | string | Yes | Interface the proxy binds to (e.g., `0.0.0.0`, `127.0.0.1`) |
| `listen_port` | int | Yes | Port exposed to clients (default: `18790`) |
| `functions_file` | string | Yes | Path to JSONL function definitions |
| `scripts_dir` | string | Yes | Directory containing shell scripts for functions |

## Model Configuration

### Routing Model (`routing`)

`routing` configures the model used for tool-routing decisions. It can be any OpenAI-compatible model provider whose model supports tool calling. For backward compatibility, the legacy top-level key `qwen` is still accepted when `routing` is absent, but new configs should use `routing`.

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `routing.base_url` | string | Yes | Base URL of the routing model endpoint (OpenAI-compatible) |
| `routing.model` | string | Yes | Model name used for routing requests; must support tool calling |
| `routing.api_key` | string | Yes | API key sent to the routing endpoint. Supports `${ENV_VAR}` substitution |

### Upstream Model (`upstream`)

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `upstream.base_url` | string | Yes | Base URL of the upstream LLM endpoint |
| `upstream.api_key` | string | Yes | API key for the upstream endpoint. Supports `${ENV_VAR}` substitution |
| `upstream.model` | string | Yes | Model name used for the final response |

## Advanced Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_tool_rounds` | int | `3` | Maximum router-model tool loop iterations before forcing upstream completion |
| `tool_exec_timeout_s` | int | `30` | Timeout for each local shell script or builtin command execution |
| `routing_timeout_s` | float | `10.0` | Timeout in seconds for each routing-model HTTP call. On timeout the router retries once with small jitter, then falls back to forwarding the request to upstream |
| `tools_base_dir` | string | - | Base directory for Python tools invoked by wrapper scripts. Sets `FR_TOOLS_BASE_DIR` env var |
| `fr_completion_check` | object | `{"enabled": true, "mode": "permissive", "always_true": false}` | Enable router model self-judgment, or force FR-only responses for router-model testing |
| `fr_context_history` | object | `{"enabled": true}` | Preserve router model context across requests |
| `fr_context_preserve` | object | `{"enabled": false}` | Never clear saved context automatically |
| `debug_logging` | object | `{"enabled": false}` | Enable detailed transcript-style debug logs |

### fr_completion_check

When enabled, after the router model successfully calls and executes tools, the router either asks the model one extra round (without tools) to judge whether the user's task is fully satisfied, or bypasses upstream entirely based on config.

- `enabled: true` turns on the completion-check path
- `mode: "permissive"` lets the completion check accept natural handoff points as complete; use `"strict"` to require fully finished tasks
- `always_true: false` keeps the normal behavior: run one extra completion-check round
- `always_true: true` enables FR-only test mode: never call upstream from chat completion handling; return the router model's reply when available, or an empty router response when the request has no router reply to return
- If the normal completion check fails or times out: falls through to normal upstream path

This typically reduces latency from ~5s to ~1s for simple tool operations. Setting `always_true: true` is mainly for testing the router model in isolation: it removes upstream from the path and trusts the router reply unconditionally.


### fr_context_history

When enabled, preserves the router model's internal message history across consecutive requests — but **only** when:
- The tool loop executed at least one tool **AND**
- The completion check judged `TASK_COMPLETE`

On every other path (no tool call, `TASK_INCOMPLETE`, max rounds exhausted, error/timeout), the saved context is cleared immediately.

This enables multi-turn commands like "retry" without re-explaining context.

### fr_context_preserve

When enabled together with `fr_context_history`, the router **never** clears saved context automatically — it persists until service restart.

Useful for accumulating context across long conversations.

### debug_logging

When enabled, writes detailed transcript-style logs to `~/.function-router/logs/router.debug.log`:

```json
{
  "debug_logging": {
    "enabled": true
  }
}
```

Inspect the log while sending real requests through the router:

```bash
tail -f ~/.function-router/logs/router.debug.log
```

The debug file rotates at 10MB and uses a compact transcript format for router-side turns:

```text
2026-05-18 14:20:31 ===== SESSION_KEY ======
2026-05-18 14:20:31 b9a63970-0685-4f6a-9a2f-example
2026-05-18 14:20:31 USER: 把系统音量调到50%
2026-05-18 14:20:31 TOOL: system_control({"category":"volume","action":"set","value":50})
2026-05-18 14:20:31 TOOL RESULT [system_control]: {"result":"ok","tool_output":"Volume set to 50%"}
2026-05-18 14:20:31 ASSISTANT: 已将系统音量调整到50%。
```

For upstream handoff, Function Router logs only the FR-managed pending context, the current user message, and the upstream assistant response:

```text
2026-05-18 14:20:35 *** START UPSTREAM ***
2026-05-18 14:20:35     PENDING_UPSTREAM_TURNS before: 1
2026-05-18 14:20:35     PENDING_UPSTREAM_TURNS injected: 1
2026-05-18 14:20:35     PENDING_UPSTREAM_TURNS after_clear: 0
2026-05-18 14:20:35     USER1: 把系统音量调到50%
2026-05-18 14:20:35     ASSISTANT1: 已将系统音量调整到50%。
2026-05-18 14:20:35     USER2: 现在音量是多少？
2026-05-18 14:20:35     ASSISTANT last: 当前系统音量是50%。
2026-05-18 14:20:35 *** FINISHED UPSTREAM ***
```

## Example

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 18790,
  "tools_base_dir": "~/.function-router/scripts",
  "routing": {
    "base_url": "https://api.example.com/v1",
    "model": "your-tool-calling-model",
    "api_key": "${ROUTING_API_KEY}"
  },
  "upstream": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "${OPENAI_API_KEY}",
    "model": "gpt-4o"
  },
  "functions_file": "functions.jsonl",
  "scripts_dir": "scripts",
  "max_tool_rounds": 6,
  "tool_exec_timeout_s": 30,
  "fr_completion_check": {
    "enabled": true,
    "mode": "permissive",
    "always_true": false
  },
  "fr_context_history": {
    "enabled": true
  },
  "fr_context_preserve": {
    "enabled": false
  },
  "debug_logging": {
    "enabled": false
  }
}
```