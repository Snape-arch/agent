# Changelog

## 0.22.0 - 2026-07-31

- Added real STEP/IGES/B-Rep import/export, exact Boolean, fillet, chamfer and repair with topology, mass-property and linear-tolerance round-trip reports.
- Added real OpenCascade/Manifold complex-part acceptance and committed RTX 5060/native GPU evidence.
- Added browser GPU timers, adapter details, native NVIDIA utilization/VRAM/temperature/power correlation and migration v17 telemetry persistence.
- Added authenticated HTTP Range asset streaming for local and S3 storage, streamed browser loading and transfer metrics.
- Added local semantic PBR/rigged/animated GLB generation plus a first-class isolated local-neural GPU provider contract.
- Added animation clip playback, skeleton inspection, ACES rendering and multi-channel PBR texture handling.

## 0.21.0 - 2026-07-31

- Added executable Lightning Trainer, Hugging Face Trainer checkpoint/resume, Keras `model.fit`, and two-process PyTorch DDP acceptance fixtures.
- Added durable callback state, rank-from-environment discovery, rank-zero reporting, Run resume, event receipts, partial metric merging, and retry-safe artifact identities.
- Expanded MLflow import to complete metric history, tags and binary artifacts; added native W&B offline `.wandb` import and MLflow/W&B bidirectional export and round-trip tools.
- Added migration v16, scheduled real-package ecosystem CI, and committed Windows acceptance evidence.

## 0.20.0 - 2026-07-31

- Added immutable multi-file and Hive-partitioned Parquet dataset versions, schema evolution checks, version manifests, and dataset lineage.
- Added cross-dataset DuckDB joins, physical plans, tenant/version-aware result caching, bounded memory and threads, asynchronous query history, cancellation, and timeout states.
- Replaced full-object S3 reads in analytical queries with DuckDB `httpfs` direct scans and Range reads; the PostgreSQL/MinIO Compose smoke now covers this path.
- Added a reproducible 10-million-row partitioned Parquet benchmark and scheduled Linux evidence job. The committed Windows run passed at a 256 MB engine limit with a 10.49 MB measured RSS delta.

## 0.19.0 - 2026-07-30

- Added an ASGI/Uvicorn production transport, extracted collection and dataset domain services, RFC-style Problem Details errors, and bounded pagination for every persistent collection API.
- Added binary object-store support, Arrow/Parquet ingestion and DuckDB pushdown queries with JSON fallback, plus migration v14 for columnar dataset metadata.
- Added real-package TensorBoard, Lightning, Transformers and Keras fixtures; concurrent SDK ingestion evidence; a configurable 60-minute PostgreSQL/MinIO soak path; and container fault injection.
- Added Chrome Playwright critical-flow and 3D visual baselines, WebGL renderer/heap/context metrics, CAD round-trip tolerance checks, and enforced Three.js deep-split bundle budgets.

## 0.18.0 - 2026-07-30

- Added OpenAPI 3.1 discovery, bounded Run/Dataset pagination, and a tested server-side filter/group/aggregate query contract.
- Added installable Python SDK packaging plus TensorBoard, MLflow file-store and JSONL history migration commands.
- Added glTF reference-integrity validation, reproducible database/data/3D scale benchmarks, a dependency-free quality gate, Ruff and coverage CI.
- Documented the architecture, testing, scale, ML, visualization and 3D production acceptance roadmap.

## 0.15.0 - 2026-07-17

- Added an auditable semantic scene-edit Agent with structure understanding, risk/cost preview, confirmation gates, durable decisions, isolated previews, Quality Agent repair cycles, stale-version protection, and atomic apply.
- Added a pluggable professional geometry Worker for Manifold, OpenCascade, and external HTTP providers with low-resolution previews, checkpoints, timeout/cancel, exact-kernel capability discovery, and high-quality replacement.
- Added migration v8, ASCII PLY mesh/colored point-cloud canonicalization, STEP/IGES asset ingestion, and API/frontend flows for Boolean, fillet, chamfer, UV unwrap, retopology, and repair.
- Added integration and contract coverage for Agent decisions and apply, professional Worker checkpoints/replacement, PLY/point-cloud import, clean install, and legacy database upgrades.

## 0.14.0 - 2026-07-17

- Added database migration v7 for asset projects, Run-to-asset timeline links, independent mesh/material/texture components, and release approvals.
- Added the unified experiment + metric + embedding + 3D checkpoint timeline to Run comparison and diagnostics.
- Added the asset production workbench with search, stage/project/tag filters, batch updates, version inspection, reference-protected deletion, archive/restore, and safe garbage collection.
- Added Python SDK helpers for embedding frames, point clouds, trajectories, vector fields, simulation frames, and model checkpoint links.
- Pinned production container images, moved CI and Docker builds to frozen pnpm installs, added Compose smoke testing, and added PostgreSQL/MinIO backup and restore automation.

## 0.13.0

- Production CI, Docker Compose release stack and upgrade/install release gate.
- Multi-file glTF import with background file processing.
- Editable OBJ/STL canonicalization to GLB.
- Voxel mesh Boolean, topology repair, vertex-cluster decimation and generated UVs.

## 0.12.0

- Editable semantic GLB/glTF scenes, natural-language operations, modifier stack, quality repair and LOD versions.
