# Reliability fixes — 2026-10-03

## Delivered

- The workspace starts without example Runs. A successful empty response clears
  old Runs; a failed response keeps the last successfully loaded data with a
  connection warning. The first Run can be created without an existing baseline.
- Example experiments require the home-page demo action. A persistent banner
  identifies simulated metrics and diagnostics. Demo experiments cannot submit
  training or attach assets; entering another workbench returns to live data.
- SDK Runs use uploaded diagnostics only. Missing confusion matrices, sample
  predictions and embeddings remain empty. Diagnostic views show an empty state
  and the actual uploaded artifact count. Missing GPU/accuracy values remain
  absent; stopped and failed Runs retain their actual status.
- The ASGI bridge forwards available response bytes immediately, watches client
  disconnects, shuts down upstream sockets, and closes buffered response objects
  outside the event loop. Legacy SSE endpoints close when their stream ends.
- The release CI job installs coverage, uvicorn, DuckDB and PyArrow before its
  release command. Browser CI also runs a production-build acceptance suite with
  real authentication and an isolated uvicorn service.

## Verification

Local Windows validation passed: 69 Python tests (70.8% coverage including branch
measurement), 17 frontend tests, 13 existing browser tests and one production
browser acceptance flow. The complete release command also passed migration,
scale/analytics, 20-flow acceptance, standalone Worker, plugin, TypeScript,
production build, bundle-budget and short soak gates. Ruff and diff whitespace
checks passed. CI execution on GitHub has not been observed in this run.

```bash
python -m pip install -r requirements-dev.txt -e ".[parquet]"
pnpm test:release
pnpm test:e2e
pnpm test:e2e:production
python -m ruff check backend sdk scripts tests
```

The production suite covers Owner bootstrap/login, empty workspace, an SDK Run,
incremental SSE events, missing diagnostics, uploaded diagnostics, logout, Viewer
login and server-side write denial. Real-socket Python tests cover stream
completion and disconnecting an idle stream without blocking other requests.

## Next priorities

Run service extraction, paginated summaries and incremental updates have now been
implemented; see [Run data flow](run-data-flow.md) for the contracts and validation.

1. Asset release and training recovery coverage is implemented and passed locally;
   the PostgreSQL/MinIO/Nginx CI gate is configured but its execution remains
   pending. See [Asset release and recovery acceptance](asset-release-recovery.md).
2. Environment-aware SDK baselines, relative p95 gates, queue-aware soak and
   timed restore rehearsal are implemented. Local repeatability, one-minute soak
   and restore checks passed; the full weekly container acceptance is configured
   but not yet executed. See [Performance and recovery acceptance](performance-recovery.md).

Local SQLite and Vite-preview acceptance does not establish PostgreSQL/MinIO,
GPU or third-party provider production readiness. The existing pending workspace
changes still need review and commits before clean-checkout CI evidence exists.
