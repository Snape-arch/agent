"""Arrow encoding and DuckDB predicate/aggregate pushdown for large datasets."""

from __future__ import annotations

import io
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from data_engine import SUPPORTED_AGGREGATES, SUPPORTED_OPERATORS


def rows_to_parquet(rows: list[dict]) -> bytes | None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), output, compression="zstd", row_group_size=65_536)
    return output.getvalue()


def parquet_to_rows(payload: bytes, *, limit: int = 100_000) -> list[dict]:
    try:
        import pyarrow.parquet as pq
        return pq.read_table(io.BytesIO(payload)).slice(0, limit).to_pylist()
    except ImportError:
        try:
            import duckdb
        except ImportError as error:
            raise RuntimeError("Parquet import requires pyarrow or duckdb") from error
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "dataset.parquet"
            path.write_bytes(payload)
            relation = duckdb.sql("SELECT * FROM read_parquet(?) LIMIT ?", params=[str(path), limit])
            columns = [item[0] for item in relation.description]
            return [dict(zip(columns, row)) for row in relation.fetchall()]


def parquet_row_count(payload: bytes) -> int:
    try:
        import pyarrow.parquet as pq
        return int(pq.ParquetFile(io.BytesIO(payload)).metadata.num_rows)
    except ImportError:
        try:
            import duckdb
        except ImportError as error:
            raise RuntimeError("Parquet metadata requires pyarrow or duckdb") from error
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "dataset.parquet"
            path.write_bytes(payload)
            return int(duckdb.connect().execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0])


def _identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("invalid field name")
    return '"' + value.replace('"', '""') + '"'


def _field_identifier(value: str) -> str:
    parts = value.split(".")
    if len(parts) > 2:
        raise ValueError("field references may contain at most one source qualifier")
    return ".".join(_identifier(part) for part in parts)


def _build_query(sources: dict[str, list[str]], request: dict) -> tuple[str, list[Any], int, int]:
    if not sources:
        raise ValueError("at least one dataset source is required")
    aliases = list(sources)
    if any(not re_alias.replace("_", "").isalnum() or re_alias[0].isdigit() for re_alias in aliases):
        raise ValueError("source aliases must be alphanumeric identifiers")
    filters = request.get("filters") or []
    groups = request.get("groupBy") or []
    aggregates = request.get("aggregates") or []
    selected = request.get("select") or []
    sort = request.get("sort") or []
    joins = request.get("joins") or []
    if isinstance(sort, dict):
        sort = [sort]
    if any(not isinstance(value, list) for value in (filters, groups, aggregates, selected, sort, joins)):
        raise ValueError("query collections must be arrays")
    limit = int(request.get("limit") or 1000)
    offset = int(request.get("offset") or 0)
    ctes: list[str] = []
    parameters: list[Any] = []
    for alias, paths in sources.items():
        if not paths:
            raise ValueError(f"source {alias} has no Parquet files")
        ctes.append(f"{_identifier(alias)} AS (SELECT * FROM read_parquet(?, union_by_name=true, hive_partitioning=true))")
        parameters.append(paths)
    from_sql = f" FROM {_identifier(aliases[0])}"
    joined = {aliases[0]}
    for join in joins:
        left = str(join.get("left") or aliases[0])
        right = str(join.get("right") or "")
        if left not in aliases or right not in aliases or left not in joined or right in joined:
            raise ValueError("joins must connect declared sources in order")
        kind = str(join.get("type") or "inner").lower()
        if kind not in {"inner", "left", "right", "full"}:
            raise ValueError("join type must be inner, left, right or full")
        conditions = join.get("on") or []
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("join requires at least one equality condition")
        predicates = []
        for condition in conditions:
            predicates.append(
                f"{_identifier(left)}.{_identifier(str(condition.get('leftField') or ''))}="
                f"{_identifier(right)}.{_identifier(str(condition.get('rightField') or ''))}"
            )
        from_sql += f" {kind.upper()} JOIN {_identifier(right)} ON {' AND '.join(predicates)}"
        joined.add(right)
    if len(aliases) > 1 and len(joined) != len(aliases):
        raise ValueError("every additional source must be connected by a join")
    where: list[str] = []
    for item in filters:
        field = _field_identifier(str(item.get("field") or ""))
        operator = str(item.get("operator") or "eq").lower()
        value = item.get("value")
        if operator not in SUPPORTED_OPERATORS:
            raise ValueError(f"unsupported filter operator: {operator}")
        if operator == "isnull":
            where.append(f"{field} IS {'NULL' if value else 'NOT NULL'}")
        elif operator == "contains":
            where.append(f"CAST({field} AS VARCHAR) ILIKE ?")
            parameters.append(f"%{value}%")
        elif operator == "in":
            values = value if isinstance(value, list) else [value]
            if not values:
                where.append("FALSE")
            else:
                where.append(f"{field} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
        elif operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("between filter requires a two-item value")
            where.append(f"{field} BETWEEN ? AND ?")
            parameters.extend(value)
        else:
            symbols = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
            where.append(f"{field} {symbols[operator]} ?")
            parameters.append(value)
    projections = [_field_identifier(str(field)) for field in groups]
    for item in aggregates:
        operation = str(item.get("op") or "").lower()
        if operation not in SUPPORTED_AGGREGATES:
            raise ValueError(f"unsupported aggregate: {operation}")
        field = str(item.get("field") or "")
        alias = _identifier(str(item.get("as") or f"{operation}_{field.replace('.', '_') or 'rows'}"))
        expression = "COUNT(*)" if operation == "count" and not field else f"{operation.upper()}({_field_identifier(field)})"
        projections.append(f"{expression} AS {alias}")
    if not projections:
        projections = []
        for item in selected:
            if isinstance(item, dict):
                projections.append(f"{_field_identifier(str(item.get('field') or ''))} AS {_identifier(str(item.get('as') or item.get('field') or ''))}")
            else:
                projections.append(_field_identifier(str(item)))
        if not projections:
            projections = [f"{_identifier(aliases[0])}.*"] if len(aliases) == 1 else ["*"]
    sql = f"WITH {','.join(ctes)} SELECT {','.join(projections)}{from_sql}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if groups:
        sql += " GROUP BY " + ",".join(_field_identifier(str(field)) for field in groups)
    if sort:
        sql += " ORDER BY " + ",".join(
            f"{_field_identifier(str(item.get('field') or ''))} {'DESC' if str(item.get('direction') or 'asc').lower() == 'desc' else 'ASC'}"
            for item in sort
        )
    return sql, parameters, limit, offset


def query_sources(
    sources: dict[str, list[str]],
    request: dict,
    *,
    maximum_result_rows: int = 10_000,
    timeout_seconds: int = 30,
    memory_limit: str = "512MB",
    threads: int = 4,
    temp_directory: str | None = None,
    configure: Callable[[Any], None] | None = None,
    on_connection: Callable[[Any], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    try:
        import duckdb
    except ImportError as error:
        raise RuntimeError("columnar query requires duckdb") from error
    sql, parameters, limit, offset = _build_query(sources, request)
    if limit < 1 or limit > maximum_result_rows or offset < 0:
        raise ValueError(f"limit must be 1..{maximum_result_rows} and offset must be non-negative")
    connection = duckdb.connect()
    timer: threading.Timer | None = None
    timed_out = threading.Event()
    started = time.perf_counter()
    try:
        connection.execute(f"SET memory_limit='{str(memory_limit).replace(chr(39), '')}'")
        connection.execute(f"SET threads={max(1, int(threads))}")
        if temp_directory:
            Path(temp_directory).mkdir(parents=True, exist_ok=True)
            safe_temp = str(temp_directory).replace("'", "''")
            connection.execute(f"SET temp_directory='{safe_temp}'")
        if configure:
            configure(connection)
        if on_connection:
            on_connection(connection)
        if is_cancelled and is_cancelled():
            raise RuntimeError("query cancelled")
        def interrupt_timeout() -> None:
            timed_out.set()
            connection.interrupt()
        timer = threading.Timer(max(1, timeout_seconds), interrupt_timeout)
        timer.daemon = True
        timer.start()
        plan_rows = connection.execute("EXPLAIN " + sql, parameters).fetchall()
        plan = "\n".join(str(row[-1]) for row in plan_rows)
        if request.get("explainOnly"):
            return {
                "rows": [],
                "columns": [],
                "plan": plan,
                "stats": {
                    "scannedRows": 0, "matchedRows": 0, "resultRows": 0, "truncated": False,
                    "provider": "duckdb-catalog", "sourceFiles": sum(len(paths) for paths in sources.values()),
                    "durationMs": round((time.perf_counter() - started) * 1000, 3), "memoryLimit": memory_limit,
                },
            }
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS result"
        total = int(connection.execute(count_sql, parameters).fetchone()[0])
        cursor = connection.execute(sql + " LIMIT ? OFFSET ?", [*parameters, limit, offset])
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        if is_cancelled and is_cancelled():
            raise RuntimeError("query cancelled")
    except Exception as error:
        message = str(error).lower()
        if timed_out.is_set():
            raise TimeoutError(f"query exceeded {timeout_seconds} seconds") from error
        if "interrupt" in message or (is_cancelled and is_cancelled()):
            raise RuntimeError("query cancelled") from error
        raise
    finally:
        if timer:
            timer.cancel()
        connection.close()
    return {
        "rows": rows,
        "columns": columns,
        "plan": plan,
        "stats": {
            "scannedRows": None,
            "matchedRows": total,
            "resultRows": len(rows),
            "truncated": offset + limit < total,
            "provider": "duckdb-catalog",
            "sourceFiles": sum(len(paths) for paths in sources.values()),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "memoryLimit": memory_limit,
        },
    }


def query_parquet(payload: bytes, request: dict, *, maximum_result_rows: int = 10_000) -> dict:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        path = Path(directory) / "dataset.parquet"
        path.write_bytes(payload)
        result = query_sources({"dataset": [str(path)]}, request, maximum_result_rows=maximum_result_rows)
        result["stats"]["provider"] = "duckdb-parquet"
        return result
