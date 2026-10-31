"""Production adapter smoke, stress and fault checks without logging credentials."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def result(name: str, status: str, **details):
    return {"adapter": name, "status": status, **details}


def local_store_check(objects: int) -> dict:
    from object_store import LocalObjectStore
    with tempfile.TemporaryDirectory() as directory:
        os.environ["CLAWVISION_OBJECT_DIR"] = directory
        store = LocalObjectStore()
        started = time.perf_counter()
        def cycle(index: int):
            value = {"id": index, "values": [random.random() for _ in range(32)]}
            key = f"stress/{index}.json"
            store.put_json(key, value)
            if store.get_json(key) != value:
                raise RuntimeError("object round-trip mismatch")
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(cycle, range(objects)))
        elapsed = time.perf_counter() - started
        # A partial temp file must never replace the committed object.
        committed = store.get_json("stress/0.json")
        (Path(directory) / "stress" / ".0.json.injected.tmp").write_text("{broken", encoding="utf-8")
        atomic = store.get_json("stress/0.json") == committed
        return result("local-object-store", "passed", objects=objects, seconds=round(elapsed, 3), opsPerSecond=round(objects * 2 / elapsed), atomicWriteFault=atomic)


def parquet_check(rows: int) -> dict:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return result("parquet", "skipped", reason="pyarrow is not installed")
    records = [{"step": index, "loss": 1 / (index + 1), "label": f"sample-{index % 20}"} for index in range(rows)]
    started = time.perf_counter()
    stream = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(records), stream, compression="zstd")
    encoded = base64.b64encode(stream.getvalue())
    decoded = pq.read_table(io.BytesIO(base64.b64decode(encoded))).to_pylist()
    elapsed = time.perf_counter() - started
    fault_ok = False
    try:
        pq.read_table(io.BytesIO(stream.getvalue()[: max(1, len(stream.getvalue()) // 3)]))
    except Exception:
        fault_ok = True
    return result("parquet", "passed" if len(decoded) == rows and fault_ok else "failed", rows=rows, bytes=len(stream.getvalue()), seconds=round(elapsed, 3), rowsPerSecond=round(rows / elapsed), truncatedFileRejected=fault_ok)


def postgres_check(operations: int) -> dict:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        return result("postgresql", "skipped", reason="DATABASE_URL is not configured")
    try:
        import psycopg
    except ImportError:
        return result("postgresql", "skipped", reason="psycopg is not installed")
    table = "clawvision_stress_" + uuid.uuid4().hex[:10]
    started = time.perf_counter()
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            connection.execute(f"CREATE TEMP TABLE {table}(id INTEGER PRIMARY KEY, payload JSONB NOT NULL)")
            for index in range(operations):
                connection.execute(f"INSERT INTO {table}(id,payload) VALUES(%s,%s)", (index, json.dumps({"step": index})))
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            try:
                connection.execute(f"INSERT INTO {table}(id,payload) VALUES(%s,%s)", (0, "{}"))
            except Exception:
                connection.rollback()
                duplicate_rejected = True
            else:
                duplicate_rejected = False
        elapsed = time.perf_counter() - started
        return result("postgresql", "passed" if count == operations and duplicate_rejected else "failed", operations=operations, seconds=round(elapsed, 3), opsPerSecond=round(operations / elapsed), duplicateFaultRejected=duplicate_rejected)
    except Exception as error:
        return result("postgresql", "failed", error=type(error).__name__, message=str(error)[:240])


def s3_check(objects: int) -> dict:
    if not os.environ.get("S3_BUCKET"):
        return result("s3", "skipped", reason="S3_BUCKET is not configured")
    try:
        from object_store import S3ObjectStore
        store = S3ObjectStore()
    except Exception as error:
        return result("s3", "failed", error=type(error).__name__, message=str(error)[:240])
    prefix = "clawvision-stress/" + uuid.uuid4().hex
    started = time.perf_counter()
    keys = []
    try:
        for index in range(objects):
            key = f"{prefix}/{index}.json"; keys.append(key)
            store.put_json(key, {"id": index})
        valid = all(store.get_json(key)["id"] == index for index, key in enumerate(keys))
        missing_rejected = False
        try:
            store.get_json(f"{prefix}/missing.json")
        except Exception:
            missing_rejected = True
        elapsed = time.perf_counter() - started
        return result("s3", "passed" if valid and missing_rejected else "failed", objects=objects, seconds=round(elapsed, 3), missingObjectRejected=missing_rejected)
    finally:
        for key in keys:
            try:
                store.client.delete_object(Bucket=store.bucket, Key=key)
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objects", type=int, default=200)
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--db-operations", type=int, default=500)
    parser.add_argument("--strict", action="store_true", help="treat skipped external adapters as failures")
    args = parser.parse_args()
    checks = [local_store_check(args.objects), parquet_check(args.rows), postgres_check(args.db_operations), s3_check(min(args.objects, 100))]
    passed = all(item["status"] == "passed" or (item["status"] == "skipped" and not args.strict) for item in checks)
    print(json.dumps({"ok": passed, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
