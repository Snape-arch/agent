# Platform operations baseline

## Signals and correlation

`GET /api/metrics` exposes Prometheus text for HTTP request rate/latency/status,
durable queue depth and age, leases, dead letters, Worker heartbeats and outcomes,
database connections/query latency/slow queries, and local/S3 object-store latency
and errors. The endpoint remains admin authenticated.

Each standalone Worker exposes the same Prometheus format on its Compose-internal
`http://worker:9091/metrics` endpoint, including Worker-side database and object
store operations. Scrape both targets and aggregate by metric labels; the Worker
endpoint is deliberately not published on a host port.

Every HTTP response contains `X-Request-ID`, `X-Trace-ID` and W3C `traceparent`.
An inbound `traceparent` is inherited; its trace context is copied into durable
task payloads and continued by the standalone Worker. Structured request and
Worker span logs include `traceId` and `spanId`. These W3C fields can be ingested
by an OpenTelemetry Collector `filelog` receiver and transformed into OTLP;
The API and Worker use the OpenTelemetry SDK to export those correlated spans to
the Compose Collector over OTLP/HTTP. The checked-in Collector uses the `debug`
exporter as an auditable local baseline; replace it with the organization's trace
backend before production and keep the OTLP endpoint private.

The database adapter currently opens one connection per unit of work. Metrics
therefore publish `clawvision_db_pool_configured 0` plus active/opened connection
counts instead of claiming pool capacity that does not exist. A production
PgBouncer deployment should use transaction mode and alert before 70% of its
configured client/server connection limits.

Prometheus alert rules are in `deploy/alerts.yml`.
Compose now loads `deploy/prometheus.yml`, `deploy/alerts.yml` and
`deploy/alertmanager.yml`. Before production startup, create an admin-scope API
token, store it in a non-repository file, and set `CLAWVISION_METRICS_TOKEN_FILE`
to that path. Replace the local Alertmanager webhook with the team's approved
paging receiver; the checked-in endpoint is intentionally a development sink.

## Initial SLOs

| Service level indicator | 30-day objective | Fast-burn page |
| --- | ---: | ---: |
| API non-5xx availability | 99.9% | 5xx ratio >5% for 10m |
| API latency, non-streaming | p95 <500ms, p99 <2s | p95 >1s for 15m |
| Accepted durable tasks reaching terminal success | 99.5% | any dead letter in 15m |
| Queue scheduling delay | p95 <30s | oldest queued >300s for 10m |
| Artifact operations | 99.9% success | S3 error ratio >1% for 10m |
| Worker heartbeat | at least one healthy Worker per required kind | age >45s for 2m |

Exclude explicit cancellations, validation errors and maintenance windows from
availability. Do not exclude timeouts, lease loss, dead letters or storage errors.

## Capacity model

Measure per task kind: arrival rate `lambda`, p95 execution time `W`, and target
utilization `U <= 0.70`. Required Worker concurrency is
`ceil(lambda * W / U)`, with at least one spare replica. Queue storage must cover
the larger of 24 hours of peak arrivals or two deployment cycles. Object-store
capacity is `daily artifact bytes * retention days * 1.25`; database capacity is
driven by metadata rows, metric points and audit retention, with 30% free disk.

Scale out when any two consecutive 15-minute windows exceed 70% Worker
utilization, queue age reaches half its SLO, database connections reach 70% of
the proxy limit, or object-store throughput reaches 70% of the measured adapter
benchmark. Re-run `concurrent_sdk_benchmark.py`, `analytics_benchmark.py` and the
60-minute soak after changing concurrency or instance shape.

## Upgrade and rollback rehearsal

1. Back up PostgreSQL and object-store manifests; record schema version, image
   digest, queue counts and dead-letter count.
2. Restore the backup into staging and run `scripts/release_check.py`, container
   smoke, migration tests and a Worker task of every enabled kind.
3. Pause new writes, allow leased tasks to finish or expire, then deploy API
   before Workers only when migrations are backward compatible.
4. Observe API errors, queue age, lease expirations, database latency and S3
   errors for at least 15 minutes before resuming full traffic.
5. Roll back application images on SLO breach. Never downgrade the database in
   place: restore the pre-upgrade database/object snapshot into a new stack,
   verify counts and checksums, then switch traffic.
6. Quarterly, time the complete restore and record RTO/RPO evidence. Initial
   targets are RPO <=15 minutes and RTO <=60 minutes.

Automated performance gates, scoped outage/restore drills and the weekly
60-minute soak are documented in [Performance and recovery acceptance](performance-recovery.md).
Local fixture evidence and pending container execution are distinguished there.
