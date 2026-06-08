# OpenClaw Session Header Patch Guide

This document explains what must change on the OpenClaw side so Function Router can receive a stable session identifier on every request.

## Why this patch exists

OpenClaw Gateway already knows the WebSocket session id from `chat.send.params.sessionKey`, but older runtime bundles do not automatically forward that value to the OpenAI-compatible provider request sent to Function Router.

Without the patch:
- FR still works as a normal tool router
- FR often falls back to a default session identity
- session-aware features degrade:
  - `fr_context_history`
  - `fr_context_preserve`
  - AutoOpenClaw exact matching of `/v1/tool_history` by `session_key`

With the patch:
- FR receives a stable `x-openclaw-session-key` header
- FR can isolate Qwen context by session
- AutoOpenClaw can match tool history strictly by session

## When you need it

Patch OpenClaw if you want any of these:
- strict session isolation between conversations
- same-session Qwen context retention
- reliable AutoOpenClaw FR history matching by `session_key`

If you do **not** patch OpenClaw, use this safer FR configuration instead:

```json
"fr_context_history": { "enabled": false },
"fr_context_preserve": { "enabled": false }
```

That compatibility mode still allows FR tool routing, but session-aware behavior is degraded.

## Patch goal

Forward:
- source: `chat.send.params.sessionKey`
- target: HTTP header `x-openclaw-session-key`

FR should then read that header and use it as the request session id.

## Where to patch

The real runtime is usually in the global install, not the source repository:

```text
/usr/local/nodejs/lib/node_modules/openclaw/dist/
```

OpenClaw bundle names change by version, so do not rely on one exact filename. Search for stable anchors such as:

- `activeSession.agent.streamFn = streamSimple`
- `applyExtraParamsToAgent(`
- `shouldInjectOllamaCompatNumCtx(`
- `pi-embedded-*.js`
- sometimes `reply-*.js`
- sometimes `plugin-sdk/dispatch-*.js`

## Minimal patch pattern

Inject the header immediately before the provider request is made by wrapping the existing `streamFn`.

```js
const openclawSessionKeyHeaderValue = typeof params.sessionKey === "string" ? params.sessionKey.trim() : "";
if (openclawSessionKeyHeaderValue) {
  const inner = activeSession.agent.streamFn;
  activeSession.agent.streamFn = (model, context, options) => inner(model, context, {
    ...options,
    headers: {
      ...options?.headers,
      "x-openclaw-session-key": openclawSessionKeyHeaderValue,
    },
  });
}
```

## Why this patch shape is recommended

- smallest behavioral change
- no OpenAI-compatible schema changes
- preserves existing provider headers
- preserves auth headers
- keeps the session id transport explicit and easy to debug

## FR-side expectation

Function Router should derive session id in this order:

1. `x-openclaw-session-key` header
2. body fields such as `sessionKey`, `session_key`, `sessionId`, `session_id`
3. nested fallbacks like `metadata` or `extra_body`
4. final fallback default

## Verification checklist

1. Restart Function Router
2. Restart OpenClaw Gateway
3. Send one real OpenClaw request through Gateway
4. Inspect FR logs

Expected result:

```text
header x-openclaw-session-key=agent:main:... session_key=agent:main:...
```

If FR still logs `session_key=default`, the most likely cause is that you patched the wrong OpenClaw bundle for the current version.

## How to tell whether this machine is already patched

Use this quick checklist:

1. Send one real request through OpenClaw Gateway to FR
2. Check FR logs or `/v1/tool_history`
3. Look for one of these outcomes

**Patched:**
- FR logs show a non-empty `x-openclaw-session-key`
- derived `session_key` is a real value such as `agent:main:...`
- `/v1/tool_history` entries record real per-request `session_key` values

**Not patched:**
- FR logs show empty header values
- derived `session_key` stays `default`
- repeated requests from different OpenClaw sessions collapse into the same fallback session bucket

A practical check is:

```bash
curl -s "http://127.0.0.1:18790/v1/tool_history?limit=5" | jq '.entries[] | {timestamp, session_key, user_message}'
```

If recent entries consistently show real OpenClaw session ids, the patch is active. If they all stay `default`, OpenClaw is still unpatched or the wrong runtime bundle was modified.

## Compatibility note for AutoOpenClaw

If FR and AutoOpenClaw are updated but OpenClaw is **not** patched:
- exact session matching may fail
- AutoOpenClaw may need to fall back to older prompt-prefix-based history matching
- this fallback is only recommended together with:
  - `fr_context_history=false`
  - `fr_context_preserve=false`

Otherwise old history attribution noise can come back.
