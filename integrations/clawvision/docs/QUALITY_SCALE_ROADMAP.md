# ClawVision engineering maturity plan

This roadmap turns the six known weaknesses into measurable release gates. A
phase is complete only when its evidence is reproducible from a clean checkout.

## P0 — architecture and API contract

- Extract validation, pagination and query logic from the HTTP handler into
  independently tested modules.
- Publish OpenAPI 3.1 at `GET /api/openapi.json`.
- Keep the current dependency-free server as the compatibility runtime while
  moving each domain behind services (`runs`, `datasets`, `assets`, `agents`).
- Next boundary: replace handler-owned transactions with service-owned units of
  work, then add an ASGI adapter without changing the public API.

Acceptance: every collection is bounded; new endpoints have contract tests;
domain modules can be tested without starting an HTTP server.

## P1 — complete test pyramid

- Fast layer: syntax/packaging gate and pure unit tests.
- Service layer: SQLite migration, data query, queues, security and SDK tests.
- API layer: real HTTP lifecycle and tenant isolation tests.
- Browser layer: Playwright critical paths on the production build.
- Adapter layer: PostgreSQL and MinIO in Docker with fault injection.
- Quality layer: Ruff and branch coverage uploaded by CI.

Acceptance: PRs run all fast/service/API checks; nightly CI runs browser,
PostgreSQL, MinIO, scale and recovery suites; branch coverage initially >= 45%
and ratchets upward rather than being reset.

## P2 — scale evidence

- Commit benchmark code, not hand-written performance claims.
- Standard profile: 10k runs, 1m metric points, 250k visualization rows and a
  250-node GLB.
- Record environment, median and p95 for every result.
- Add PostgreSQL profiles for concurrent SDK writers, SSE readers, queue leases,
  object-store throughput and restore after forced worker termination.

Acceptance: standard profile produces a versioned JSON report; p95 regression
over the previous release is < 20%; a 60-minute soak has no orphaned tasks.

## P3 — ML ecosystem

- Native callbacks: Lightning, Hugging Face Trainer and Keras.
- Migration: TensorBoard event files, MLflow file-store runs and W&B-style JSONL
  histories.
- Next: PyTorch autolog context, distributed rank aggregation, MLflow tracking
  URI importer, W&B public API importer and OpenTelemetry resource correlation.

Acceptance: each adapter has a tiny real-framework fixture and produces the same
canonical Run/Metric/Artifact/Lineage contract.

## P4 — general data visualization

- Server-side filters, projection, sorting, grouping and aggregates are the
  canonical dashboard query contract.
- Add an Arrow/Parquet object representation and DuckDB execution provider for
  data over the JSON scan threshold.
- Add histogram/binning, window functions, joins and approximate aggregates.
- Move linked selections to a shared filter state and virtualize large tables.

Acceptance: 1m Parquet rows can be filtered and aggregated without loading all
rows into the browser; the same VisualizationSpec renders reproducibly.

## P5 — production 3D

- Validate GLB header plus accessors, buffer views, buffers, materials, textures
  and hierarchy references.
- Add golden assets for GLB/GLTF/OBJ/STL round trips and compare topology,
  bounds, materials, UVs and texture hashes.
- Add browser screenshot baselines, WebGL context-loss recovery and large-asset
  memory budgets.
- Keep parametric CAD and learned Text-to-3D providers isolated behind separate
  plugin/provider contracts.

Acceptance: supported fixtures round-trip within documented tolerances; 250-node
assets stay interactive; malformed references fail before release or export.

## Commands and evidence

```bash
python scripts/quality_gate.py
python -m unittest discover -s tests -v
python scripts/scale_benchmark.py --profile quick
python scripts/scale_benchmark.py --profile standard --output docs/benchmarks/latest.json
pnpm build
```

Current closure is the first vertical slice across P0–P5: OpenAPI and pagination,
pure service boundaries, ecosystem importers, a server-side query contract,
reference-integrity 3D gates, and reproducible benchmarks. The remaining items
above are intentionally stated as release evidence, not claimed as complete.
