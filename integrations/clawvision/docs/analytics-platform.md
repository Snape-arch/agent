# Analytics Platform

ClawVision 0.20 upgrades the original single-dataset Parquet query path into a
versioned, multi-dataset analytics service.

## Storage and catalog

- A dataset version owns an immutable manifest of one or more Parquet objects.
- Hive-style object paths (`field=value/part-xxxxx.parquet`) preserve partition
  values and let DuckDB prune files before scanning row groups.
- The catalog records current version, schema version, partition columns, row
  count, byte size, parent version, and a machine-readable schema diff.
- Adding fields is compatible by default. Removing fields or changing their
  types returns HTTP 409 unless `allowBreakingSchema` is explicitly enabled.
- Dataset lineage records source and target versions, relation type, and the
  transform description.

Create a partitioned dataset:

```json
{
  "name": "metrics",
  "partitionBy": ["split"],
  "files": [
    {"format": "json", "partitions": {"split": "train"}, "content": [{"run_id": 1, "loss": 0.8}]},
    {"format": "json", "partitions": {"split": "eval"}, "content": [{"run_id": 2, "loss": 0.5}]}
  ]
}
```

`POST /api/datasets/{datasetId}/versions` creates a new immutable version.
`GET /api/datasets/{datasetId}/versions` and `/lineage` expose its history.

## Query execution

`POST /api/analysis/query` executes synchronously. `POST /api/analysis/queries`
creates a persistent asynchronous query that can be inspected or cancelled.
Every request can set a bounded timeout, thread count, result limit, and memory
limit. The service returns the DuckDB physical plan with file count and timing.

Cross-dataset joins use declared aliases and equality conditions:

```json
{
  "sources": [
    {"datasetId": "data_metrics", "alias": "m"},
    {"datasetId": "data_labels", "alias": "l"}
  ],
  "joins": [
    {"left": "m", "right": "l", "type": "inner",
     "on": [{"leftField": "run_id", "rightField": "run_id"}]}
  ],
  "select": [
    {"field": "m.loss", "as": "loss"},
    {"field": "l.label", "as": "label"}
  ],
  "timeoutSeconds": 30,
  "memoryLimit": "512MB",
  "cacheTtlSeconds": 300
}
```

Results are cached by tenant, immutable source-version signatures, and normalized
query input. `explainOnly: true` returns a plan without executing the data query.
Cancellation calls DuckDB's interrupt API, while timeout uses an independent
server timer. The async state model distinguishes `completed`, `cancelled`,
`timed_out`, and `failed`.

## S3/MinIO range reads

For local storage, DuckDB receives validated local file paths. For S3/MinIO, it
receives `s3://bucket/key` URIs and the `httpfs` configuration. Consequently,
Parquet footers and selected row groups are fetched through HTTP Range requests;
the API process does not call `get_bytes` or materialize complete objects.
The production image pre-installs `httpfs`, and the Compose smoke test exercises
this path against real MinIO.

## Reproducible scale evidence

Run:

```bash
python scripts/analytics_benchmark.py --profile full \
  --output docs/benchmarks/analytics-10m.json
```

The committed Windows result covers 10,000,000 rows across 10 partitioned files
with a 256 MB DuckDB limit. It matched 5,000,000 filtered rows in 110.75 ms,
used a measured 10.49 MB RSS delta, and passed the physical Parquet-scan check.
These figures describe the recorded machine, not a universal latency guarantee.
The scheduled CI job repeats the same benchmark on Linux and uploads the report.
