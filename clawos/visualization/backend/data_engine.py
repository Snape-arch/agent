"""Deterministic server-side filtering and aggregation for visualization data."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

SUPPORTED_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "between", "isnull"}
SUPPORTED_AGGREGATES = {"count", "sum", "avg", "min", "max", "median"}


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "isnull":
        return (actual is None) is bool(expected)
    if operator == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if operator == "in":
        return actual in (expected if isinstance(expected, list) else [expected])
    if operator == "between":
        if not isinstance(expected, list) or len(expected) != 2:
            raise ValueError("between filter requires a two-item value")
        return actual is not None and expected[0] <= actual <= expected[1]
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if actual is None:
        return False
    try:
        return {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}[operator]
    except TypeError:
        return False


def _filtered(rows: Iterable[dict], filters: list[dict]) -> Iterable[dict]:
    for row in rows:
        matches = True
        for item in filters:
            field = str(item.get("field") or "")
            operator = str(item.get("operator") or "eq").lower()
            if not field:
                raise ValueError("each filter requires a field")
            if operator not in SUPPORTED_OPERATORS:
                raise ValueError(f"unsupported filter operator: {operator}")
            if not _compare(row.get(field), operator, item.get("value")):
                matches = False
                break
        if matches:
            yield row


def _aggregate(values: list[Any], operation: str) -> int | float | None:
    if operation == "count":
        return len(values)
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    if not numeric:
        return None
    if operation == "sum":
        return sum(numeric)
    if operation == "avg":
        return sum(numeric) / len(numeric)
    if operation == "min":
        return min(numeric)
    if operation == "max":
        return max(numeric)
    if operation == "median":
        return median(numeric)
    raise ValueError(f"unsupported aggregate: {operation}")


def query_rows(rows: list[dict], request: dict, *, maximum_result_rows: int = 10_000) -> dict:
    """Execute a safe query contract used by charts and linked dashboards."""
    filters = request.get("filters") or []
    group_by = request.get("groupBy") or []
    aggregates = request.get("aggregates") or []
    select = request.get("select") or []
    if not isinstance(filters, list) or not isinstance(group_by, list) or not isinstance(aggregates, list):
        raise ValueError("filters, groupBy and aggregates must be arrays")
    if len(filters) > 32 or len(group_by) > 8 or len(aggregates) > 32:
        raise ValueError("query complexity limit exceeded")
    limit = int(request.get("limit") or 1000)
    offset = int(request.get("offset") or 0)
    if limit < 1 or limit > maximum_result_rows or offset < 0:
        raise ValueError(f"limit must be 1..{maximum_result_rows} and offset must be non-negative")
    matching = list(_filtered(rows, filters))
    scanned = len(rows)
    if aggregates:
        for aggregate in aggregates:
            if str(aggregate.get("op") or "").lower() not in SUPPORTED_AGGREGATES:
                raise ValueError(f"unsupported aggregate: {aggregate.get('op')}")
        buckets: dict[tuple, list[dict]] = defaultdict(list)
        for row in matching:
            buckets[tuple(row.get(field) for field in group_by)].append(row)
        output = []
        for key, bucket in buckets.items():
            result = {field: key[index] for index, field in enumerate(group_by)}
            for item in aggregates:
                operation = str(item.get("op")).lower()
                field = str(item.get("field") or "")
                alias = str(item.get("as") or f"{operation}_{field or 'rows'}")
                result[alias] = _aggregate([row.get(field) for row in bucket] if field else bucket, operation)
            output.append(result)
    else:
        output = [{field: row.get(field) for field in select} for row in matching] if select else matching
    sort = request.get("sort") or []
    if isinstance(sort, dict):
        sort = [sort]
    for item in reversed(sort):
        field = str(item.get("field") or "")
        reverse = str(item.get("direction") or "asc").lower() == "desc"
        output.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=reverse)
    total = len(output)
    result_rows = output[offset:offset + limit]
    return {
        "rows": result_rows,
        "columns": list(dict.fromkeys(key for row in result_rows for key in row)),
        "stats": {"scannedRows": scanned, "matchedRows": len(matching), "resultRows": total, "truncated": offset + limit < total},
    }
