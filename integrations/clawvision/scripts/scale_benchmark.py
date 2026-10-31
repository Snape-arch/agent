"""Repeatable local scale evidence for storage, querying and 3D packaging."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_engine import query_rows  # noqa: E402
from mesh_generator import compile_obj  # noqa: E402
from mesh_quality import assess_mesh  # noqa: E402
from mesh_postprocess import postprocess_to_glb  # noqa: E402


def timed(operation, repeats: int = 1) -> tuple[object, dict]:
    samples = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = operation()
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return result, {
        "medianMs": round(statistics.median(samples), 3),
        "p95Ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3),
        "samples": len(samples),
    }


def database_benchmark(run_count: int, metrics_per_run: int) -> dict:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        connection = sqlite3.connect(Path(directory) / "scale.db")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
        CREATE TABLE runs(id TEXT PRIMARY KEY,name TEXT,tenant_id TEXT,created_at TEXT);
        CREATE TABLE metrics(run_id TEXT,step INTEGER,value REAL,created_at TEXT,PRIMARY KEY(run_id,step));
        CREATE INDEX runs_tenant_time ON runs(tenant_id,created_at DESC);
        CREATE INDEX metrics_run_step ON metrics(run_id,step);
        """)
        timestamp = datetime.now(timezone.utc).isoformat()
        _, insert = timed(lambda: connection.executemany(
            "INSERT INTO runs VALUES(?,?,?,?)",
            ((f"run_{index}", f"experiment-{index}", "tenant-scale", f"{timestamp}-{index:08d}") for index in range(run_count)),
        ))
        _, metric_insert = timed(lambda: connection.executemany(
            "INSERT INTO metrics VALUES(?,?,?,?)",
            ((f"run_{run}", step, 1 / (step + 1), timestamp) for run in range(run_count) for step in range(metrics_per_run)),
        ))
        connection.commit()
        _, list_query = timed(lambda: connection.execute(
            "SELECT * FROM runs WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100 OFFSET ?",
            ("tenant-scale", max(0, run_count - 100)),
        ).fetchall(), repeats=20)
        _, metric_query = timed(lambda: connection.execute(
            "SELECT step,value FROM metrics WHERE run_id=? ORDER BY step", (f"run_{run_count // 2}",)
        ).fetchall(), repeats=20)
        connection.close()
    return {
        "runs": run_count,
        "metrics": run_count * metrics_per_run,
        "insertRuns": insert,
        "insertMetrics": metric_insert,
        "deepPageQuery": list_query,
        "runMetricQuery": metric_query,
    }


def data_benchmark(row_count: int) -> dict:
    rows = [
        {"model": f"model-{index % 20}", "step": index // 20, "loss": 1 / (1 + index % 1000), "accuracy": (index % 100) / 100}
        for index in range(row_count)
    ]
    result, timing = timed(lambda: query_rows(rows, {
        "filters": [{"field": "accuracy", "operator": "gte", "value": .5}],
        "groupBy": ["model"],
        "aggregates": [{"field": "loss", "op": "avg", "as": "meanLoss"}, {"op": "count", "as": "points"}],
        "sort": {"field": "meanLoss"},
    }), repeats=5)
    return {"rows": row_count, "query": timing, "groups": len(result["rows"]), "stats": result["stats"]}


def asset_benchmark(parts: int) -> dict:
    plan = {
        "name": "scale-asset",
        "parts": [
            {"name": f"part-{index}", "shape": "box", "size": [.2, .2, .2], "position": [index % 20, index // 20, 0], "color": "#55aaff"}
            for index in range(parts)
        ],
    }
    def release_asset():
        obj, generated = compile_obj(plan, "standard")
        payload, packaged = postprocess_to_glb(obj, "obj", plan["name"])
        return payload, {**generated, **packaged}
    result, timing = timed(release_asset, repeats=3)
    payload, stats = result
    quality = assess_mesh(payload, "glb")
    return {"parts": parts, "bytes": len(payload), "compile": timing, "generator": stats, "quality": quality}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "standard"), default="standard")
    parser.add_argument("--output")
    args = parser.parse_args()
    sizes = {"quick": (500, 20, 20_000, 40), "standard": (10_000, 100, 250_000, 250)}
    runs, metrics_per_run, rows, parts = sizes[args.profile]
    report = {
        "schemaVersion": 1,
        "profile": args.profile,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "database": database_benchmark(runs, metrics_per_run),
        "dataEngine": data_benchmark(rows),
        "assetPipeline": asset_benchmark(parts),
    }
    # Regression ceilings are deliberately broad enough for shared CI runners.
    report["passed"] = (
        report["database"]["deepPageQuery"]["p95Ms"] < 500
        and report["database"]["runMetricQuery"]["p95Ms"] < 500
        and report["dataEngine"]["query"]["p95Ms"] < (2_500 if args.profile == "quick" else 15_000)
        and report["assetPipeline"]["quality"]["contract"]["valid"]
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
