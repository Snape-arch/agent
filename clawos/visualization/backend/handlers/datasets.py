"""Datasets adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import base64
import csv
import io
import json
import os
import re
import uuid


class DatasetsHandler:
    runtime: HandlerRuntime

    def _create_dataset(self, body: dict, existing_dataset_id: str | None = None) -> None:
        raw_files = body.get("files")
        if raw_files is None:
            raw_files = [{"format": body.get("format", "json"), "content": body.get("content"), "partitions": body.get("partitions", {})}]
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty array")
        partition_by = body.get("partitionBy") or []
        if not isinstance(partition_by, list) or not all(isinstance(field, str) and field for field in partition_by):
            raise ValueError("partitionBy must be an array of field names")
        maximum_rows = max(1, int(os.environ.get("CLAWVISION_DATASET_MAX_ROWS", "25000000")))
        preview_limit = max(1, int(os.environ.get("CLAWVISION_DATASET_PREVIEW_ROWS", "10000")))
        decoded: list[dict] = []
        preview: list[dict] = []
        total_rows = 0
        per_file_preview = max(1, preview_limit // len(raw_files))
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict):
                raise ValueError("each file must be an object")
            data_format = str(item.get("format") or body.get("format") or "json").lower()
            content = item.get("content")
            payload: bytes | None = None
            if data_format == "csv":
                rows = list(csv.DictReader(io.StringIO(str(content or ""))))
            elif data_format == "json":
                parsed = json.loads(content) if isinstance(content, str) else content
                rows = parsed if isinstance(parsed, list) else parsed.get("data", []) if isinstance(parsed, dict) else []
            elif data_format == "parquet":
                payload = base64.b64decode(str(content or ""), validate=True)
                count = self.runtime.parquet_row_count(payload)
                rows = self.runtime.parquet_to_rows(payload, limit=per_file_preview)
            else:
                raise ValueError("format must be csv, json or parquet")
            if not rows or not all(isinstance(row, dict) for row in rows):
                raise ValueError(f"file {index} must contain at least one object row")
            count = count if data_format == "parquet" else len(rows)
            total_rows += count
            if total_rows > maximum_rows:
                raise ValueError(f"dataset exceeds {maximum_rows} rows")
            partitions = item.get("partitions") or {}
            if not isinstance(partitions, dict) or any(field not in partitions for field in partition_by):
                raise ValueError("every file must declare values for all partitionBy fields")
            decoded.append({"format": data_format, "rows": rows, "payload": payload, "rowCount": count, "partitions": partitions})
            preview.extend(rows[:per_file_preview])
        fields = self.runtime.infer_fields(preview)
        dataset_id = existing_dataset_id or str(body.get("id") or f"data_{uuid.uuid4().hex[:12]}")
        name = str(body.get("name") or dataset_id)
        created_at = self.runtime.now_iso()
        if existing_dataset_id:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                current = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, self.principal.tenant_id)).fetchone()
                parent = db.execute("SELECT schema_json FROM dataset_versions WHERE dataset_id=? AND tenant_id=? ORDER BY version DESC LIMIT 1", (dataset_id, self.principal.tenant_id)).fetchone()
            if not current:
                raise self.runtime.NotFoundError("dataset not found")
            name = str(body.get("name") or current["name"])
            changes = self.runtime.schema_diff(self.runtime.json_value(parent["schema_json"], []) if parent else self.runtime.json_value(current["schema_json"], []), fields)
            if not changes["compatible"] and not body.get("allowBreakingSchema"):
                raise self.runtime.ConflictError("schema evolution removes or changes existing fields", detail=changes)
        version_token = uuid.uuid4().hex[:12]
        manifest: list[dict] = []
        staged_files: list[tuple[str, bytes]] = []
        stored_bytes = 0
        for index, item in enumerate(decoded):
            payload = item["payload"]
            if payload is None:
                payload = self.runtime.rows_to_parquet(self.runtime.coerce_rows(item["rows"], fields))
            if payload is None:
                raise RuntimeError("Parquet support requires pyarrow")
            partition_path = "/".join(
                f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', field)}={re.sub(r'[^A-Za-z0-9_.-]+', '_', str(item['partitions'][field]))}"
                for field in partition_by
            )
            key = f"tenants/{self.principal.tenant_id}/datasets/{dataset_id}/versions/{version_token}/"
            if partition_path:
                key += partition_path + "/"
            key += f"part-{index:05d}.parquet"
            staged_files.append((key, payload))
            stored_bytes += len(payload)
            manifest.append({"key": key, "format": "parquet", "rowCount": item["rowCount"], "byteSize": len(payload), "partitions": item["partitions"]})
        preview_rows = self.runtime.coerce_rows(preview, fields)
        preview_bytes = json.dumps(preview_rows, ensure_ascii=False).encode()
        self.runtime.reserve_storage(self.principal.tenant_id, stored_bytes + len(preview_bytes))
        for key, payload in staged_files:
            self.runtime.OBJECT_STORE.put_bytes(key, payload, "application/vnd.apache.parquet")
        object_key = self.runtime.OBJECT_STORE.put_json(
            f"tenants/{self.principal.tenant_id}/datasets/{dataset_id}/versions/{version_token}/preview.json",
            preview_rows,
        )
        if not existing_dataset_id:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                db.execute(
                    "INSERT INTO datasets(id,name,format,schema_json,object_key,row_count,created_at,tenant_id,storage_format,columnar_key,byte_size,current_version_id,schema_version,partition_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (dataset_id, name, "multi" if len(raw_files) > 1 else decoded[0]["format"], "[]", object_key, 0, created_at, self.principal.tenant_id, "parquet", manifest[0]["key"], 0, None, 1, json.dumps(partition_by), created_at),
                )
        version = self.runtime.DatasetCatalog(self.runtime.connect, self.runtime.OBJECT_STORE).register_version(
            dataset_id,
            self.principal.tenant_id,
            fields,
            manifest,
            partition_by=partition_by,
            allow_breaking=bool(body.get("allowBreakingSchema")),
            lineage=body.get("lineage") if isinstance(body.get("lineage"), list) else None,
        )
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute("UPDATE datasets SET name=?,object_key=?,format=?,updated_at=? WHERE id=? AND tenant_id=?", (name, object_key, "multi" if len(raw_files) > 1 else decoded[0]["format"], created_at, dataset_id, self.principal.tenant_id))
        self._json({"data": {"id": dataset_id, "name": name, "format": "multi" if len(raw_files) > 1 else decoded[0]["format"], "storageFormat": "parquet", "schema": fields, "rows": preview_rows, "rowCount": total_rows, "partitionBy": partition_by, "version": version, "createdAt": created_at}}, HTTPStatus.CREATED)


    def _query_dataset(self, dataset_id: str, body: dict) -> None:
        result = self.runtime.analysis_service().execute(self.principal.tenant_id, body, dataset_id)
        self._json({"data": result})


    def _save_visualization_spec(self, body: dict) -> None:
        spec = body.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("spec must be an object")
        spec_id = str(body.get("id") or f"viz_{uuid.uuid4().hex[:12]}")
        created_at = self.runtime.now_iso()
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            owner = db.execute("SELECT tenant_id FROM visualization_specs WHERE id=?", (spec_id,)).fetchone()
            if owner and owner["tenant_id"] != self.principal.tenant_id:
                raise PermissionError("visualization spec belongs to another tenant")
            current = db.execute("SELECT * FROM visualization_specs WHERE id=? AND tenant_id=?", (spec_id,self.principal.tenant_id)).fetchone()
            share_token = current["share_token"] if current else uuid.uuid4().hex[:16]
            db.execute("""INSERT INTO visualization_specs(id,name,dataset_id,spec,share_token,is_public,version,created_at,updated_at,tenant_id)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,dataset_id=excluded.dataset_id,
              spec=excluded.spec,is_public=excluded.is_public,version=visualization_specs.version+1,updated_at=excluded.updated_at""",
              (spec_id, str(body.get("name") or "Untitled visualization"), body.get("datasetId"), json.dumps(spec, ensure_ascii=False), share_token, 1 if body.get("isPublic", True) else 0, 1, created_at, created_at,self.principal.tenant_id))
            row = db.execute("SELECT * FROM visualization_specs WHERE id=? AND tenant_id=?", (spec_id,self.principal.tenant_id)).fetchone()
        self._json({"data": {"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": self.runtime.json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]}}, HTTPStatus.CREATED)
