"""Generate and query a partitioned Parquet corpus with a hard DuckDB memory cap."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from columnar_engine import query_sources  # noqa: E402


def rss_bytes() -> int:
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        get_memory = ctypes.windll.kernel32.K32GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        get_memory.restype = ctypes.c_int
        if not get_memory(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.WorkingSetSize)
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), default="full")
    parser.add_argument("--rows", type=int)
    parser.add_argument("--memory-limit", default="256MB")
    parser.add_argument("--max-rss-delta-mb", type=int, default=512)
    parser.add_argument("--output")
    args = parser.parse_args()
    rows = args.rows or (100_000 if args.profile == "quick" else 10_000_000)
    partitions = 10
    rows_per_file = (rows + partitions - 1) // partitions
    try:
        import duckdb
    except ImportError as error:
        raise SystemExit("install the parquet extra: pip install -e .[parquet]") from error
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        generator = duckdb.connect()
        paths: list[str] = []
        generation_started = time.perf_counter()
        generated_rows = 0
        for partition in range(partitions):
            count = min(rows_per_file, rows - generated_rows)
            if count <= 0:
                break
            folder = root / f"bucket={partition}"
            folder.mkdir()
            path = folder / "part.parquet"
            start = generated_rows
            generator.execute(
                f"COPY (SELECT range + {start} AS id, ((range + {start}) % 1000)::DOUBLE / 1000 AS value "
                f"FROM range({count})) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)",
                [str(path)],
            )
            paths.append(str(path))
            generated_rows += count
        generator.close()
        generation_ms = (time.perf_counter() - generation_started) * 1000
        baseline = rss_bytes()
        peak = baseline
        stop = threading.Event()

        def sample_memory() -> None:
            nonlocal peak
            while not stop.wait(0.01):
                peak = max(peak, rss_bytes())

        sampler = threading.Thread(target=sample_memory, daemon=True)
        sampler.start()
        query_started = time.perf_counter()
        try:
            result = query_sources(
                {"events": paths},
                {
                    "filters": [{"field": "id", "operator": "gte", "value": rows // 2}],
                    "groupBy": ["bucket"],
                    "aggregates": [{"op": "count", "as": "rows"}, {"field": "value", "op": "avg", "as": "meanValue"}],
                    "sort": {"field": "bucket"},
                    "cache": False,
                },
                memory_limit=args.memory_limit,
                timeout_seconds=300,
                threads=min(4, os.cpu_count() or 1),
                temp_directory=str(root / "spill"),
            )
        finally:
            stop.set()
            sampler.join(timeout=1)
        query_ms = (time.perf_counter() - query_started) * 1000
        delta = max(0, peak - baseline)
        report = {
            "schemaVersion": 1,
            "profile": args.profile,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
            "files": len(paths),
            "partitioned": True,
            "memoryLimit": args.memory_limit,
            "baselineRssMb": round(baseline / 1024 / 1024, 2),
            "peakRssMb": round(peak / 1024 / 1024, 2),
            "rssDeltaMb": round(delta / 1024 / 1024, 2),
            "maxRssDeltaMb": args.max_rss_delta_mb,
            "generationMs": round(generation_ms, 2),
            "queryMs": round(query_ms, 2),
            "matchedRows": sum(int(item["rows"]) for item in result["rows"]),
            "resultRows": result["stats"]["matchedRows"],
            "resultGroups": len(result["rows"]),
            "sourceFiles": result["stats"]["sourceFiles"],
            "planHasParquetScan": "READ_PARQUET" in result["plan"],
        }
        report["passed"] = (
            report["matchedRows"] == rows - rows // 2
            and report["sourceFiles"] == len(paths)
            and report["planHasParquetScan"]
            and report["rssDeltaMb"] <= args.max_rss_delta_mb
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
