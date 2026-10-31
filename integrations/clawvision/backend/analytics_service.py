"""Versioned dataset catalog and controlled DuckDB query execution."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from columnar_engine import query_sources
from errors import ConflictError, NotFoundError, ValidationError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schema_diff(previous: list[dict], current: list[dict]) -> dict:
    before = {str(item.get("name")): str(item.get("type")) for item in previous}
    after = {str(item.get("name")): str(item.get("type")) for item in current}
    added = [{"name": name, "type": after[name]} for name in after.keys() - before.keys()]
    removed = [{"name": name, "type": before[name]} for name in before.keys() - after.keys()]
    changed = [{"name": name, "from": before[name], "to": after[name]} for name in before.keys() & after.keys() if before[name] != after[name]]
    return {"added": sorted(added, key=lambda item: item["name"]), "removed": sorted(removed, key=lambda item: item["name"]), "typeChanged": sorted(changed, key=lambda item: item["name"]), "compatible": not removed and not changed}


class DatasetCatalog:
    def __init__(self, connect, object_store):
        self.connect = connect
        self.object_store = object_store

    def register_version(
        self,
        dataset_id: str,
        tenant_id: str,
        schema: list[dict],
        manifest: list[dict],
        *,
        partition_by: list[str] | None = None,
        allow_breaking: bool = False,
        lineage: list[dict] | None = None,
    ) -> dict:
        partition_by = partition_by or []
        timestamp = _now()
        with self.connect() as db:
            dataset = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)).fetchone()
            if not dataset:
                raise NotFoundError("dataset not found")
            parent = db.execute("SELECT * FROM dataset_versions WHERE dataset_id=? AND tenant_id=? ORDER BY version DESC LIMIT 1", (dataset_id, tenant_id)).fetchone()
            previous_schema = json.loads(parent["schema_json"]) if parent else []
            changes = schema_diff(previous_schema, schema) if parent else {"added": schema, "removed": [], "typeChanged": [], "compatible": True}
            if parent and not changes["compatible"] and not allow_breaking:
                raise ConflictError("schema evolution removes or changes existing fields", detail=changes)
            version = int(parent["version"]) + 1 if parent else 1
            version_id = f"dsv_{uuid.uuid4().hex[:12]}"
            row_count = sum(int(item.get("rowCount") or 0) for item in manifest)
            byte_size = sum(int(item.get("byteSize") or 0) for item in manifest)
            schema_version = int(dataset["schema_version"] or 1) if "schema_version" in dataset.keys() else 1
            if parent and previous_schema != schema:
                schema_version += 1
            db.execute(
                "INSERT INTO dataset_versions(id,dataset_id,tenant_id,version,schema_json,manifest_json,partition_by,row_count,byte_size,parent_version_id,change_summary,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (version_id, dataset_id, tenant_id, version, json.dumps(schema, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False), json.dumps(partition_by), row_count, byte_size, parent["id"] if parent else None, json.dumps(changes, ensure_ascii=False), timestamp),
            )
            first_key = manifest[0]["key"] if manifest else dataset["columnar_key"]
            db.execute(
                "UPDATE datasets SET schema_json=?,row_count=?,byte_size=?,columnar_key=?,storage_format='parquet',current_version_id=?,schema_version=?,partition_by=?,updated_at=? WHERE id=? AND tenant_id=?",
                (json.dumps(schema, ensure_ascii=False), row_count, byte_size, first_key, version_id, schema_version, json.dumps(partition_by), timestamp, dataset_id, tenant_id),
            )
            for source in lineage or []:
                source_id = str(source.get("datasetId") or "")
                source_row = db.execute("SELECT current_version_id FROM datasets WHERE id=? AND tenant_id=?", (source_id, tenant_id)).fetchone()
                if not source_row:
                    raise ValidationError(f"lineage source is not visible: {source_id}")
                db.execute(
                    "INSERT INTO dataset_lineage(id,tenant_id,target_dataset_id,target_version_id,source_dataset_id,source_version_id,relation,transform_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (f"dsl_{uuid.uuid4().hex[:12]}", tenant_id, dataset_id, version_id, source_id, source.get("versionId") or source_row["current_version_id"], str(source.get("relation") or "derived"), json.dumps(source.get("transform") or {}, ensure_ascii=False), timestamp),
                )
        return {"id": version_id, "datasetId": dataset_id, "version": version, "schemaVersion": schema_version, "schema": schema, "manifest": manifest, "partitionBy": partition_by, "rowCount": row_count, "byteSize": byte_size, "parentVersionId": parent["id"] if parent else None, "changeSummary": changes, "createdAt": timestamp}

    def versions(self, dataset_id: str, tenant_id: str) -> list[dict]:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)).fetchone():
                raise NotFoundError("dataset not found")
            rows = db.execute("SELECT * FROM dataset_versions WHERE dataset_id=? AND tenant_id=? ORDER BY version DESC", (dataset_id, tenant_id)).fetchall()
        return [self._version(row) for row in rows]

    def lineage(self, dataset_id: str, tenant_id: str) -> dict:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)).fetchone():
                raise NotFoundError("dataset not found")
            incoming = db.execute("SELECT * FROM dataset_lineage WHERE target_dataset_id=? AND tenant_id=? ORDER BY created_at", (dataset_id, tenant_id)).fetchall()
            outgoing = db.execute("SELECT * FROM dataset_lineage WHERE source_dataset_id=? AND tenant_id=? ORDER BY created_at", (dataset_id, tenant_id)).fetchall()
        convert = lambda row: {**dict(row), "transform": json.loads(row["transform_json"])}
        return {"upstream": [convert(row) for row in incoming], "downstream": [convert(row) for row in outgoing]}

    def resolve_sources(self, request: dict, tenant_id: str, primary_dataset_id: str | None = None) -> tuple[dict[str, list[str]], list[dict]]:
        requested = request.get("sources")
        if requested is None:
            if not primary_dataset_id:
                raise ValidationError("sources are required")
            requested = [{"datasetId": primary_dataset_id, "alias": "dataset"}]
        if not isinstance(requested, list) or not requested:
            raise ValidationError("sources must be a non-empty array")
        resolved: dict[str, list[str]] = {}
        signatures: list[dict] = []
        with self.connect() as db:
            for index, item in enumerate(requested):
                dataset_id = str(item.get("datasetId") or "")
                alias = str(item.get("alias") or f"source{index}")
                dataset = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)).fetchone()
                if not dataset:
                    raise NotFoundError(f"dataset not found: {dataset_id}")
                version = None
                if item.get("versionId"):
                    version = db.execute("SELECT * FROM dataset_versions WHERE id=? AND dataset_id=? AND tenant_id=?", (item["versionId"], dataset_id, tenant_id)).fetchone()
                elif item.get("version"):
                    version = db.execute("SELECT * FROM dataset_versions WHERE dataset_id=? AND version=? AND tenant_id=?", (dataset_id, int(item["version"]), tenant_id)).fetchone()
                elif "current_version_id" in dataset.keys() and dataset["current_version_id"]:
                    version = db.execute("SELECT * FROM dataset_versions WHERE id=? AND tenant_id=?", (dataset["current_version_id"], tenant_id)).fetchone()
                if version:
                    manifest = json.loads(version["manifest_json"])
                    version_id = version["id"]
                elif dataset["columnar_key"]:
                    manifest = [{"key": dataset["columnar_key"], "rowCount": dataset["row_count"], "byteSize": dataset["byte_size"], "partitions": {}}]
                    version_id = "legacy"
                else:
                    raise ValidationError(f"dataset has no columnar files: {dataset_id}")
                resolved[alias] = [self.object_store.query_uri(entry["key"]) for entry in manifest]
                signatures.append({"alias": alias, "datasetId": dataset_id, "versionId": version_id, "files": [entry["key"] for entry in manifest]})
        return resolved, signatures

    @staticmethod
    def _version(row) -> dict:
        return {"id": row["id"], "datasetId": row["dataset_id"], "version": row["version"], "schema": json.loads(row["schema_json"]), "manifest": json.loads(row["manifest_json"]), "partitionBy": json.loads(row["partition_by"]), "rowCount": row["row_count"], "byteSize": row["byte_size"], "parentVersionId": row["parent_version_id"], "changeSummary": json.loads(row["change_summary"]), "createdAt": row["created_at"]}


class AnalysisQueryService:
    def __init__(self, connect, object_store):
        self.connect = connect
        self.object_store = object_store
        self.catalog = DatasetCatalog(connect, object_store)
        self.executor = ThreadPoolExecutor(max_workers=max(1, int(os.environ.get("CLAWVISION_ANALYTICS_CONCURRENCY", "2"))), thread_name_prefix="analytics")
        self.connections: dict[str, Any] = {}
        self.lock = threading.RLock()

    def submit(self, tenant_id: str, request: dict, primary_dataset_id: str | None = None) -> dict:
        query_id = f"query_{uuid.uuid4().hex[:12]}"
        timestamp = _now()
        timeout = min(max(int(request.get("timeoutSeconds") or 30), 1), int(os.environ.get("CLAWVISION_ANALYTICS_MAX_TIMEOUT", "300")))
        normalized = {**request, **({"primaryDatasetId": primary_dataset_id} if primary_dataset_id else {})}
        with self.connect() as db:
            db.execute("INSERT INTO analysis_queries(id,tenant_id,status,request_json,timeout_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (query_id, tenant_id, "queued", json.dumps(normalized, ensure_ascii=False), timeout, timestamp, timestamp))
        self.executor.submit(self._run, query_id, tenant_id, request, primary_dataset_id, timeout)
        return self.get(query_id, tenant_id, include_result=False)

    def execute(self, tenant_id: str, request: dict, primary_dataset_id: str | None = None) -> dict:
        query_id = f"sync_{uuid.uuid4().hex[:12]}"
        timeout = min(max(int(request.get("timeoutSeconds") or 30), 1), int(os.environ.get("CLAWVISION_ANALYTICS_MAX_TIMEOUT", "300")))
        return self._execute_query(query_id, tenant_id, request, primary_dataset_id, timeout)

    def _execute_query(self, query_id: str, tenant_id: str, request: dict, primary_dataset_id: str | None, timeout: int) -> dict:
        sources, signatures = self.catalog.resolve_sources(request, tenant_id, primary_dataset_id)
        cache_key = hashlib.sha256(json.dumps({"tenant": tenant_id, "sources": signatures, "query": request}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        now = _now()
        self._prune_cache(tenant_id, now)
        if request.get("cache", True):
            with self.connect() as db:
                cached = db.execute("SELECT * FROM analysis_cache WHERE cache_key=? AND tenant_id=? AND expires_at>?", (cache_key, tenant_id, now)).fetchone()
                if cached:
                    db.execute("UPDATE analysis_cache SET last_accessed_at=? WHERE cache_key=?", (now, cache_key))
                    result = self.object_store.get_json(cached["result_key"])
                    result["stats"]["cached"] = True
                    result["cacheKey"] = cache_key
                    return result
        cancelled = lambda: self._cancel_requested(query_id, tenant_id)
        temp_directory = Path(os.environ.get("CLAWVISION_ANALYTICS_TEMP_DIR") or Path(os.environ.get("CLAWVISION_DATA_DIR", "data")) / "duckdb-tmp")
        temp_directory.mkdir(parents=True, exist_ok=True)
        result = query_sources(
            sources,
            request,
            maximum_result_rows=max(1, int(os.environ.get("CLAWVISION_DATA_QUERY_MAX_RESULT", "10000"))),
            timeout_seconds=timeout,
            memory_limit=str(request.get("memoryLimit") or os.environ.get("CLAWVISION_ANALYTICS_MEMORY_LIMIT", "512MB")),
            threads=min(max(int(request.get("threads") or 4), 1), 16),
            temp_directory=str(temp_directory),
            configure=self.object_store.configure_duckdb,
            on_connection=lambda connection: self._register(query_id, connection),
            is_cancelled=cancelled,
        )
        result["stats"]["cached"] = False
        result["cacheKey"] = cache_key
        if request.get("cache", True) and not request.get("explainOnly"):
            cached_key = self.object_store.put_json(f"tenants/{tenant_id}/analysis/cache/{cache_key}.json", result)
            finished = _now()
            ttl = min(max(int(request.get("cacheTtlSeconds") or 300), 1), 86_400)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
            payload_size = len(json.dumps(result, ensure_ascii=False).encode())
            with self.connect() as db:
                db.execute(
                    "INSERT INTO analysis_cache(cache_key,tenant_id,result_key,row_count,byte_size,expires_at,created_at,last_accessed_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(cache_key) DO UPDATE SET result_key=excluded.result_key,row_count=excluded.row_count,byte_size=excluded.byte_size,expires_at=excluded.expires_at,last_accessed_at=excluded.last_accessed_at",
                    (cache_key, tenant_id, cached_key, len(result["rows"]), payload_size, expires, finished, finished),
                )
        return result

    def _run(self, query_id: str, tenant_id: str, request: dict, primary_dataset_id: str | None, timeout: int) -> None:
        timestamp = _now()
        with self.connect() as db:
            db.execute("UPDATE analysis_queries SET status='running',started_at=?,updated_at=? WHERE id=? AND tenant_id=?", (timestamp, timestamp, query_id, tenant_id))
        try:
            result = self._execute_query(query_id, tenant_id, request, primary_dataset_id, timeout)
            if self._cancel_requested(query_id, tenant_id):
                raise RuntimeError("query cancelled")
            result_key = self.object_store.put_json(f"tenants/{tenant_id}/analysis/{query_id}.json", result)
            plan = result.get("plan")
            finished = _now()
            ttl = min(max(int(request.get("cacheTtlSeconds") or 300), 1), 86_400)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
            payload_size = len(json.dumps(result, ensure_ascii=False).encode())
            with self.connect() as db:
                db.execute("UPDATE analysis_queries SET status='completed',result_key=?,plan_json=?,cache_key=?,cached=?,finished_at=?,updated_at=? WHERE id=? AND tenant_id=?", (result_key, json.dumps({"text": plan}), result["cacheKey"], 1 if result["stats"]["cached"] else 0, finished, finished, query_id, tenant_id))
                if not result["stats"]["cached"] and request.get("cache", True):
                    db.execute("INSERT INTO analysis_cache(cache_key,tenant_id,result_key,row_count,byte_size,expires_at,created_at,last_accessed_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET result_key=excluded.result_key,row_count=excluded.row_count,byte_size=excluded.byte_size,expires_at=excluded.expires_at,last_accessed_at=excluded.last_accessed_at", (result["cacheKey"], tenant_id, result_key, len(result["rows"]), payload_size, expires, finished, finished))
        except Exception as error:
            finished = _now()
            status = "cancelled" if "cancel" in str(error).lower() else "timed_out" if isinstance(error, TimeoutError) else "failed"
            with self.connect() as db:
                db.execute("UPDATE analysis_queries SET status=?,error=?,finished_at=?,updated_at=? WHERE id=? AND tenant_id=?", (status, str(error), finished, finished, query_id, tenant_id))
        finally:
            with self.lock:
                self.connections.pop(query_id, None)

    def get(self, query_id: str, tenant_id: str, *, include_result: bool = True) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM analysis_queries WHERE id=? AND tenant_id=?", (query_id, tenant_id)).fetchone()
        if not row:
            raise NotFoundError("analysis query not found")
        result = self.object_store.get_json(row["result_key"]) if include_result and row["result_key"] else None
        return {"id": row["id"], "status": row["status"], "request": json.loads(row["request_json"]), "result": result, "plan": json.loads(row["plan_json"]) if row["plan_json"] else None, "error": row["error"], "cacheKey": row["cache_key"], "cached": bool(row["cached"]), "cancelRequested": bool(row["cancel_requested"]), "timeoutSeconds": row["timeout_seconds"], "startedAt": row["started_at"], "finishedAt": row["finished_at"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    def cancel(self, query_id: str, tenant_id: str) -> dict:
        timestamp = _now()
        with self.connect() as db:
            row = db.execute("SELECT status FROM analysis_queries WHERE id=? AND tenant_id=?", (query_id, tenant_id)).fetchone()
            if not row:
                raise NotFoundError("analysis query not found")
            if row["status"] in {"completed", "failed", "timed_out", "cancelled"}:
                return self.get(query_id, tenant_id, include_result=False)
            db.execute("UPDATE analysis_queries SET cancel_requested=1,updated_at=? WHERE id=? AND tenant_id=?", (timestamp, query_id, tenant_id))
        with self.lock:
            connection = self.connections.get(query_id)
        if connection:
            connection.interrupt()
        return self.get(query_id, tenant_id, include_result=False)

    def _register(self, query_id: str, connection) -> None:
        with self.lock:
            self.connections[query_id] = connection

    def _prune_cache(self, tenant_id: str, now: str) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT cache_key,result_key FROM analysis_cache WHERE tenant_id=? AND expires_at<=? LIMIT 100", (tenant_id, now)).fetchall()
            for row in rows:
                db.execute("DELETE FROM analysis_cache WHERE cache_key=? AND tenant_id=?", (row["cache_key"], tenant_id))
        for row in rows:
            try:
                self.object_store.delete(row["result_key"])
            except (FileNotFoundError, KeyError):
                pass

    def _cancel_requested(self, query_id: str, tenant_id: str) -> bool:
        if query_id.startswith("sync_"):
            return False
        with self.connect() as db:
            row = db.execute("SELECT cancel_requested FROM analysis_queries WHERE id=? AND tenant_id=?", (query_id, tenant_id)).fetchone()
        return bool(row and row["cancel_requested"])
