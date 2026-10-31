# ClawVision in ClawOS

This is a source snapshot of the user's ClawVision working tree, based on
`65afd74a0fc170a32340a36594afd42207c1b5a9`, including newer uncommitted source.
`SOURCE_SNAPSHOT.json` preserves original file fingerprints before integration
changes. The original project and its Git history are untouched.

The source project declares Apache-2.0 in pyproject.toml; original attribution
and source notices are retained. No model weights, original databases, artifacts,
credentials, node_modules or Git metadata are imported.

ClawOS serves the rebuilt React app at `/academy/vision/` and gateways its API
under `/api/vision/service/`. The experiment backend runs in a separately owned
loopback child process with its own data directory. Only ClawOS's direct local
owner can operate this first integration. Document collaborator permissions do
not grant experiment or training access. Upstream standalone authentication and
tenant APIs remain in the source, but are not presented as integrated team SSO.

ClawOS credentials/environment are not inherited, models are not automatically
loaded, and the service starts only on explicit request. Built-in simulator and
local deterministic geometry are distinct from real training/model inference.

Integration changes: API/resource namespace helpers, ClawOS launch gate and
navigation, shared warm-paper color tokens, typography/layout, an authenticated
loopback worker entry, runtime supervision and bounded streaming gateway.
Standalone source mode retains the original AuthGate; use
`node node_modules/vite/bin/vite.js --base / --host 127.0.0.1` with a separately
configured standalone backend. The default production build targets ClawOS.

Install the tested optional data adapters into an isolated directory with:

```powershell
<app-python> -m pip install --only-binary=:all: --target clawos/output/vision-libs -r integrations/clawvision/requirements-integration.lock.txt
```

They are used only in the child experiment service. The desktop build copies
them into that service's separate `runtime-libs`, without merging them into the
main ClawOS Python environment. Neither directory is committed. GPU/ML/CAD
extras remain optional and require their own installation and validation.

Build the frontend with `node clawos/scripts/build_vision_frontend.mjs`; its
staging, cache and previous compiled assets stay in output. The actual product
assets and third-party notices are published to `clawos/static/vision`.

The integrated data page loads saved datasets instead of silently choosing
sample rows. Dashboard saves are private; reopening uses a saved visualization
ID. Charts describe the size of their preview rather than implying a whole
dataset scan. Built-in examples require explicit selection and remain labeled.
