"""Domain services shared by the legacy HTTP and ASGI transports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from api_contract import Pagination, page_meta
from columnar_engine import query_parquet
from data_engine import query_rows
from errors import NotFoundError, ValidationError


@dataclass
class Page:
    rows: list
    pagination: dict


class CollectionService:
    """Bounded collection reads with controlled SQL identifiers."""

    ALLOWED = {
        "audit_logs", "studio_generations", "studio_scene_versions", "agent_runs",
        "scene_agent_runs", "parameter_snapshots", "asset_projects", "runs", "jobs",
        "datasets", "visualization_specs", "model_assets", "model_scenes", "analysis_queries", "three_telemetry", "tasks", "durable_tasks",
    }

    @classmethod
    def list(
        cls,
        db,
        table: str,
        pagination: Pagination,
        *,
        where: str = "tenant_id=?",
        values: tuple | list = (),
        order_by: str = "created_at DESC",
        select: str = "*",
        mapper: Callable[[Any], Any] = dict,
    ) -> Page:
        if table not in cls.ALLOWED:
            raise ValidationError("unsupported collection")
        parameters = tuple(values)
        total = int(db.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}", parameters).fetchone()["count"])
        rows = db.execute(
            f"SELECT {select} FROM {table} WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            (*parameters, pagination.page_size, pagination.offset),
        ).fetchall()
        return Page([mapper(row) for row in rows], page_meta(pagination, total))


class DatasetService:
    def __init__(self, connect, object_store):
        self.connect = connect
        self.object_store = object_store

    def get(self, dataset_id: str, tenant_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)).fetchone()
        if not row:
            raise NotFoundError("dataset not found")
        return row

    def query(self, dataset_id: str, tenant_id: str, request: dict, *, maximum_scan: int, maximum_result: int) -> dict:
        row = self.get(dataset_id, tenant_id)
        keys = set(row.keys())
        columnar_key = row["columnar_key"] if "columnar_key" in keys else None
        if columnar_key:
            try:
                return query_parquet(self.object_store.get_bytes(columnar_key), request, maximum_result_rows=maximum_result)
            except RuntimeError:
                # Optional provider absent: the canonical JSON representation is
                # retained specifically for a dependency-free fallback.
                pass
        if int(row["row_count"]) > maximum_scan:
            raise ValidationError(f"dataset has {row['row_count']} rows; configured scan limit is {maximum_scan}")
        rows = self.object_store.get_json(row["object_key"])
        if not isinstance(rows, list):
            raise ValidationError("dataset object is not a row array")
        return query_rows(rows, request, maximum_result_rows=maximum_result)
