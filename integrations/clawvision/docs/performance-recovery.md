# Performance regression and recovery acceptance

## SDK baselines and relative gates

`scripts/concurrent_sdk_benchmark.py` starts a fresh authenticated uvicorn/SQLite
fixture by default. `--url` targets an existing disposable deployment. The SDK
driver verifies completed status, every persisted step, loss and accuracy values;
successful SDK calls alone no longer count as ingestion success. Offline spool
files, missing points or failed requests fail the benchmark.

The default profile uses four concurrent clients, 32 Runs per round, 40 steps,
batch size 20, three measured rounds and four excluded warmup Runs. Each report
includes 96 measured samples, 3,840 verified points, per-round timings, throughput
and nearest-rank p95 for ingestion and detail reads. Ingestion timing excludes
the verification read; total throughput includes verification. These Run timings
cover multiple requests and are not a single-request latency SLO.

Environment evidence records measurement-host OS, architecture, CPU, CPU count,
Python, storage adapters, transport and an operator environment label. Git revision,
dirty state and source/SDK digests identify uncommitted code. A fingerprint matches
the comparable environment fields; source digests remain separate so application
changes can be compared. External reports describe the measurement host and
adapter kinds, not automatically discovered remote server capacity.

`performance_gate.py` rejects different environments, workloads or SDK drivers,
missing provenance, fewer than 20 samples, incomplete correctness evidence and
invalid latency values. Both p95 values must remain within 1.35 times the baseline.
The initial 35% tolerance accommodates shared-runner noise and is configurable;
it is not an absolute latency objective. Do not compare old schema-v1 benchmark
files, different hardware or different Run sizes.

```bash
python scripts/concurrent_sdk_benchmark.py --output output/playwright/performance/baseline.json
python scripts/concurrent_sdk_benchmark.py --output output/playwright/performance/candidate.json
python scripts/performance_gate.py --baseline output/playwright/performance/baseline.json \
  --candidate output/playwright/performance/candidate.json --output output/playwright/performance/gate.json
```

The CI `performance-regression` job runs the PR base API and candidate API
sequentially on the same runner, using the same current SDK driver and fresh data
directories. Push/manual/scheduled runs record candidate evidence; PR runs also
enforce the relative gate. Local repeated-current-code measurements establish
repeatability, not a measured improvement over a prior commit.

## Soak and Worker coverage

`soak_test.py` uses real authentication, bounded summary reads, persisted metric
and event checks, and periodic simulator jobs executed by a standalone Worker.
It drains its own jobs, traverses all task pages and checks durable completion.
The task API now paginates the database rather than truncating to 100 tasks before
pagination. Reports include actual elapsed duration, p95 cycle time, failures,
queue outcomes and unfinished tasks. Exception evidence records types without
credentials or response bodies.

```bash
python scripts/soak_test.py --minutes 1 --output output/playwright/soak-one-minute.json
python scripts/soak_test.py --minutes 60 --output output/playwright/soak-60m.json
```

The weekly container job runs production browser acceptance, including forced
Worker termination and checkpoint recovery, then PostgreSQL/MinIO outage tests,
restore rehearsal and a full 60-minute soak. Outage recovery verifies retained
artifact bytes and subsequent metric writes, not only a green health response.
Stopped services are restarted in `finally` paths. Evidence is uploaded even on
failure before the scoped disposable stack is removed.

## Backup restore rehearsal

`backup_rehearsal.py` defaults to an isolated local fixture. It seeds metrics,
events, ingestion receipts, an artifact and a versioned dataset. SQLite backup
captures committed WAL data; object files are copied while this owned fixture is
quiescent. The database/object snapshot is restored into a different temporary
directory. All application table counts and row digests, and all object byte
digests, must match. Hidden object filenames are included. API reads, subsequent
metric/cursor writes and artifact uploads are checked after the comparison.

```bash
python scripts/backup_rehearsal.py --output output/playwright/restore-local.json
```

Compose mode requires explicit disposable source and fresh restore project names.
It stops source writers before taking both database and object snapshots, uses
`pg_dump`/`pg_restore` and MinIO mirror, and verifies restored Run reads, metric
writes and object reads/writes. Only PostgreSQL/MinIO are provisioned in the
restore target, avoiding host port conflicts. Acceptance images are shared with
the prebuilt source stack. The source restarts on failure; only the newly created
target is removed. Existing target containers or volumes are rejected.

```bash
python scripts/backup_rehearsal.py --project clawvision-chaos \
  --restore-project clawvision-restore-ci --compose-file docker-compose.yml \
  --compose-file compose.e2e.yml --output output/playwright/restore-compose.json
```

The measured restore bound defaults to 3,600 seconds. Local timing includes
API read/write verification. Container timing covers fresh storage provisioning,
import, integrity and application data-service read/write checks; it does not
measure a traffic switch, Nginx startup or complete infrastructure disaster
recovery. RPO is explicitly unverified: this drill does not establish a periodic
backup interval. Bucket policies/version history, deployment secrets, image
distribution and other infrastructure configuration need separate recovery plans.

## Local evidence and remaining execution

Results are in [Local reliability evidence](benchmarks/reliability-local.json).
The fixture is Windows/Python 3.14.2 with SQLite, local objects and uvicorn:

- Two final SDK measurements verified 96 Runs / 3,840 points each; both relative
  p95 gates passed. They use the same dirty working-tree source digest.
- One-minute soak: 121 SDK Runs and 13 standalone Worker jobs completed, zero
  failures and zero unfinished tasks; p95 cycle time was 320.927 ms.
- Restore: 47 tables and three object files matched; API read/write checks passed.
  Measured restore time was 1.656 seconds for this small fixture.
- Complete release passed with 95 Python tests, 72.1% overall coverage and 25
  frontend tests. The three production browser flows passed again after task
  pagination changes. Ruff and diff whitespace checks passed.

Docker is unavailable on this host. The 60-minute container soak, PostgreSQL/MinIO
fault/restore drill and PR-base performance comparison are configured but have
not been observed running. One-minute local soak and small-fixture restore timings
do not establish production capacity, RTO/RPO or hour-long stability.
