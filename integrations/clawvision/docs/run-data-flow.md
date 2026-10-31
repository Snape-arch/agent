# Run services, pagination and incremental updates

## Service boundary

`backend/run_service.py` owns Run snapshots, summary queries, metric/event/parameter/
artifact ingestion, idempotent batches and status transitions. HTTP handlers handle
authentication, authorization, request parsing, response status and stream transport.
Each public service operation receives the authenticated tenant. The internal
`server.get_run` compatibility helper remains available for trusted callers.
Job scheduling and training lineage retain their existing handlers.

Writes commit metrics, events, parameters, status and ingestion receipts together.
Object uploads and quota reservation happen before the write transaction. This
retains the existing object-store behavior; orphan-object cleanup is not part of
this change. Snapshots read metadata, cursor and histories in one database snapshot
(SQLite explicit transaction; PostgreSQL repeatable read).

## List and detail contracts

```text
GET /api/runs?summary=1&page=1&pageSize=25&q=training
GET /api/runs/{id}
```

The summary response includes `data`, `pagination` and tenant-wide status `counts`.
Each summary contains metadata, `revision`, `latestMetric`, `metricCount` and
`artifactCount`. It excludes metric/log histories and artifact content. A nonempty
summary page performs six bounded queries regardless of its number of Runs and
never reads the object store. Results sort by `created_at DESC, id DESC` with a
tenant/date/ID index. `q` matches a literal, case-insensitive name substring;
SQL wildcard characters are escaped. Pagination is offset-based, so newly created
Runs can shift page boundaries between requests.

The detail response includes complete metrics, logs, events, artifacts and `cursor`.
Existing clients can still use `/api/runs` without `summary=1` for the legacy full
response. Pagination validation continues to enforce page >= 1 and pageSize 1–500.

## Durable incremental contract

Migration 18 adds a per-Run revision and a `run_changes` journal. SQLite and
PostgreSQL triggers track Run metadata and metric/event/artifact insertions,
updates and deletions. Separate Workers and direct database writers therefore
advance cursors without relying on process-local notifications. Existing Runs
start at revision zero; the initial detail snapshot contains their prior history.

```text
GET /api/runs/{id}/changes?after={cursor}&limit=100
GET /api/runs/{id}/stream?incremental=1&after={cursor}
```

Both return the same delta shape: `id`, `run`, `cursor`, `hasMore`, `metrics`,
`events`, `artifacts`, `removedMetrics`, `removedEvents` and `removedArtifacts`.
The changes endpoint wraps it in `data`. The stream sends `event: run-delta` with
`id: cursor`; `Last-Event-ID` is accepted when `after` is omitted. The legacy
stream continues sending full `event: run` snapshots.

Clients first load a detail snapshot and then subscribe after its cursor. Advance
only to the returned **cursor**, not `run.revision`: metadata describes the latest
snapshot and may be ahead of a bounded batch. Drain while `hasMore` is true.
Repeated keys within a batch are collapsed and their latest committed values are
returned; this is an idempotent synchronization protocol, not historical event
reconstruction. Upsert metrics by step, events by numeric ID and artifacts by ID;
apply removed keys and ignore already-applied cursors. Corrections to an old step
are included, even when the largest step has not changed.

Changes batches are limited to 100 journal records by default and 500 maximum.
The stream drains pending batches before ending a terminal Run, includes idle
keepalives, and periodically closes so clients can resume. Negative or invalid
cursors and cursors ahead of the Run return HTTP 400 before streaming headers.
An ahead-of-Run cursor requires a fresh detail snapshot, such as after restoring
an older database backup. The journal is retained without pruning in this version;
retention/compaction must define a minimum valid cursor before deleting old records.

## Frontend lifecycle

- Current-page summaries refresh every 15 seconds after the previous request
  completes. Search debounces for 300 ms, searches all Runs and resets to page one.
  Obsolete requests are aborted and late results cannot replace the active page.
- Home statistics use tenant-wide counts, independent of page size or search.
- Overview loads its selected Run and up to two comparison Runs; diagnostics
  loads the selected Run; comparison loads up to ten selected Runs. Other views
  do not load histories. A viewed-Run cache retains at most 40 details.
- The selected detail uses incremental SSE; other viewed Runs poll cursor deltas
  every five seconds, draining bounded batches while `hasMore` is true. One SSE
  connection leaves HTTP/1.1 capacity for searches, uploads and controls. Changes
  include same-step corrections, deletion merges and derived diagnostics.
  Search pauses obsolete detail connections while summary requests are pending.
  Reconnects resume the last applied cursor with
  bounded backoff. Terminal Runs reconnect every 15 seconds to discover later
  artifact uploads or resumes. Leaving a view cancels requests, readers and timers.
- Parameter Lab training remains owned by backend Workers. The workspace no
  longer runs its own background browser training loop.

## Validation scope

Service tests cover tenant boundaries, stable pagination, escaped search, no
summary object reads, separate Worker writes, old-step corrections, bounded
delta draining, deletions, receipt/data/cursor rollback and snapshot consistency.
Frontend tests cover request cancellation, late-response races, debounced search,
controlled polling, detail caching, cleanup, ordered/idempotent merges and SSE
reconnection. Real-socket uvicorn tests cover compatibility streams and draining
205 changed metrics across three terminal batches. The production browser flow
covers a 26-Run workspace, global counts, next-page navigation, cross-page search,
on-demand details, live deltas and real authentication.

The complete release, existing browser and production browser gates are run
locally. This validation uses SQLite and the local object store. PostgreSQL
trigger syntax and migration execution, MinIO and a deployed reverse proxy still
need live acceptance in their target environment.

Initial Run refactoring results: 75 Python tests (71.2% overall coverage; Run
service 94.1%), 24 frontend tests, 13 existing browser tests and one production
browser flow. Subsequent asset/recovery acceptance and transport limits are
documented in [Asset release and recovery acceptance](asset-release-recovery.md).
The release command passed quality, migrations 1–18, scale/analytics, 20-flow
acceptance, standalone Worker, plugin boundaries, TypeScript, build/bundle budget
and short soak checks. The Run service now has an 85% coverage release floor.
