# Asset release and training recovery acceptance

## Changes

Asset approval/rejection and every catalog path that moves an asset to `release`
require both the admin role and admin token scope. This includes direct PATCH,
batch edits and uploads with `metadata.assetStage`. Researchers may submit pending
releases. The backend records the authenticated reviewer rather than a submitted
identity; approval and the asset stage commit together. PATCH requests also pass
the resource ownership guard. The UI hides unauthorized approval controls and
reports failed approvals.

Standalone Workers load the persisted checkpoint before retrying real training.
A missing checkpoint fails explicitly. Completed training redelivery does not
repeat training or increment the parent completion count. API restart preserves
live Worker leases and Run state. Lease expiry cleanup rechecks expiry when it
writes, so a concurrent heartbeat is preserved.

PyTorch checkpoints now retain CPU/CUDA RNG state with model and optimizer state.
Restoring a final-epoch checkpoint computes diagnostics in evaluation mode without
requiring another epoch. Checkpoint deserialization uses `weights_only=True`.
Legacy checkpoints without RNG state remain readable, but cannot reproduce the
exact subsequent random sequence.

The workspace keeps one Run SSE connection; other viewed Runs drain cursor deltas
every five seconds. Search cancels obsolete detail connections while the new
summary request is pending. This leaves HTTP/1.1 connection capacity for controls
and searches even when comparing ten Runs. Poll timers are removed after firing.
Collection count queries use named rows compatible with PostgreSQL dict cursors.

## Browser and Python evidence

`pnpm test:e2e:production` uses the production build, real authentication and
uvicorn. Its three sequential flows cover:

1. Empty workspace, live Run deltas, uploaded diagnostics, 26-Run pagination,
   cross-page search and Viewer write denial.
2. Owner approval, reload persistence, authenticated reviewer, ranged asset
   download and Researcher rejection on approval/PATCH/batch publication paths.
3. Standalone Worker process termination after checkpoint step 2, lease expiry,
   a second attempt that runs only steps 3–6, preservation of earlier metrics,
   browser deltas and uploaded diagnostics without a page reload.

Recovery browser acceptance uses `tests/fixtures/training_recovery.py`, a JSONL
process probe. It deliberately pauses after its first checkpoint; it tests the
queue, object store, process boundary and browser transport, not ML accuracy.
Local Windows acceptance kills only its own Worker process tree.

Separate Python tests exercise real PyTorch: final-epoch checkpoint restoration
and equality of remaining-epoch metrics to uninterrupted training with dropout.
These tests skip explicitly when PyTorch is unavailable. Other regression tests
cover missing checkpoints, completed redelivery, API restart with a live lease,
lease renewal during cleanup, tenant boundaries and admin token scope.

## PostgreSQL / MinIO / Nginx CI gate

The `compose-smoke` CI job builds an isolated `clawvision-e2e` Compose project
with `compose.e2e.yml`, runs the same production browser suite through Nginx,
then runs catalog/direct-S3 smoke checks and strict adapter checks. Browser
acceptance asserts PostgreSQL, S3 and Nginx are actually in use. Strict adapter
checks fail on unavailable dependencies rather than silently skipping them.
Logs and browser failure evidence are uploaded before the isolated volumes are
removed. The Worker starts after API health, avoiding concurrent initial schema
creation in this acceptance stack.

The acceptance override replaces the trainer with the process probe and sets a
five-second Worker lease. Normal deployment retains the default PyTorch script
and thirty-second lease. Use this override only in a fresh disposable project.
The suite creates its Owner and changes training Worker lifecycle; it is not a
read-only test for an existing deployment.

Example on a Docker-enabled host, from the repository root (Bash):

```bash
export CLAWVISION_E2E_BASE_URL=http://127.0.0.1:8080
export CLAWVISION_E2E_COMPOSE_PROJECT=clawvision-e2e
docker compose -p clawvision-e2e -f docker-compose.yml -f compose.e2e.yml up -d --build --wait
pnpm test:e2e:production
CLAWVISION_SMOKE_EMAIL=owner@production.test \
CLAWVISION_SMOKE_PASSWORD=production-owner-password python scripts/container_smoke.py
docker compose -p clawvision-e2e -f docker-compose.yml -f compose.e2e.yml exec -T api \
  python scripts/stress_adapters.py --strict --objects 16 --rows 1000 --db-operations 100
```

The passwords above belong only to disposable acceptance accounts. Local results
use SQLite/local objects. Docker, PostgreSQL, MinIO and Nginx execution was not
available on this Windows host; the new container CI gate has not been observed
running. GPU checkpoint recovery and third-party providers remain unverified.

## Local validation results (2026-10-03)

- `pnpm test:release`: passed, including 83 Python tests, 72.1% overall coverage,
  94.1% Run-service coverage, 25 frontend tests, migrations 1–18, quick scale and
  analytics checks, 20-flow acceptance, standalone Worker checks, plugin boundaries,
  TypeScript, production build, bundle budget and short soak.
- `pnpm test:e2e`: 13 existing browser flows passed.
- `pnpm test:e2e:production`: all three production browser flows passed.
- Ruff and diff whitespace checks passed; workflow and Compose YAML parsed.
  Docker Compose semantic validation and container execution remain pending CI.
