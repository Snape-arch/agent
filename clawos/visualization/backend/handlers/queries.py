"""Queries adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse
import re
import uuid


class QueriesHandler:
    runtime: HandlerRuntime

    def do_GET(self) -> None:  # noqa: N802
        self.request_id=self.headers.get("X-Request-ID") or "req_"+uuid.uuid4().hex[:12]
        parsed_url = urlparse(self.path); path = parsed_url.path; query = parse_qs(parsed_url.query)
        if path == "/api/health":
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                database_ok = bool(db.execute("SELECT 1 AS ok").fetchone())
            storage = self.runtime.OBJECT_STORE.health_check()
            workers=self.runtime.worker_statuses()
            return self._json({"ok": database_ok and storage["ok"], "database": self.runtime.database_label(), "databaseKind": "postgresql" if self.runtime.is_postgres() else "sqlite", "objectStore": storage, "workers": workers, "queueRecovery": True, "time": self.runtime.now_iso()})
        if path == "/api/openapi.json":
            return self._json(self.runtime.openapi_document("0.22.0"))
        if path == "/api/metrics":
            if not self._authorize(path, admin=True): return
            self.runtime.queue_metrics()
            workers=self.runtime.worker_statuses();self.runtime.gauge("clawvision_workers_healthy",sum(1 for worker in workers if worker["healthy"]))
            for worker in workers:
                self.runtime.gauge("clawvision_worker_healthy",1 if worker["healthy"] else 0,worker=worker["workerId"])
                self.runtime.gauge("clawvision_worker_heartbeat_age_seconds",worker["ageSeconds"],worker=worker["workerId"])
                self.runtime.gauge("clawvision_worker_tasks_completed",worker["completed"],worker=worker["workerId"])
                self.runtime.gauge("clawvision_worker_tasks_failed",worker["failed"],worker=worker["workerId"])
            with self.runtime.DB_LOCK,self.runtime.connect() as db:runs=db.execute("SELECT status,COUNT(*) AS count FROM runs GROUP BY status").fetchall()
            for row in runs:self.runtime.gauge("clawvision_runs",int(row["count"]),status=row["status"])
            payload=self.runtime.render_prometheus().encode();self.send_response(200);self.send_header("Content-Type","text/plain; version=0.0.4");self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload);return
        if not self._authorize(path): return
        if path == "/api/auth/me": return self._json({"data": {"userId": self.principal.user_id, "tenantId": self.principal.tenant_id, "role": self.principal.role, "scopes": self.principal.scopes}})
        if path == "/api/auth/tokens": return self._json(self._page_values(self.runtime.list_tokens(self.principal), query))
        if path == "/api/auth/members": return self._json(self._page_values(self.runtime.list_members(self.principal), query))
        if path == "/api/quotas": return self._json({"data": self.runtime.quota_status(self.principal)})
        if path == "/api/tasks":
            return self._json(self._page_table("durable_tasks", query, order_by="created_at DESC,id DESC", mapper=self.runtime.serialize_task))
        if path == "/api/audit-logs":
            if not self.principal.permits("admin"): return self._json({"error": "admin role required"}, HTTPStatus.FORBIDDEN)
            return self._json(self._page_table("audit_logs", query, default=100))
        if path == "/api/studio/templates":
            return self._json({"data": self.runtime.TEMPLATES})
        if path == "/api/studio/text-to-3d/providers":
            return self._json({"data": self.runtime.list_text3d_providers()})
        if path == "/api/geometry/providers":
            return self._json({"data": self.runtime.geometry_provider_catalog()})
        if path == "/api/telemetry/3d":
            payload = self._page_table("three_telemetry", query, default=100, order_by="created_at DESC")
            payload["data"] = [{**dict(row), "payload": self.runtime.json_value(row["payload"], {})} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/training/providers":
            return self._json({"data": self.runtime.training_provider_catalog()})
        training_match = re.fullmatch(r"/api/training-jobs/([^/]+)", path)
        if training_match:
            with self.runtime.DB_LOCK, self.runtime.connect() as db: row = db.execute("SELECT * FROM training_jobs WHERE id=? AND tenant_id=?", (training_match.group(1), self.principal.tenant_id)).fetchone()
            return self._json({"data": {**dict(row), "result": self.runtime.json_value(row["result"], {})} if row else None}, HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        if path == "/api/studio/generations":
            payload = self._page_table("studio_generations", query, order_by="updated_at DESC")
            payload["data"] = [{"id": row["id"], "name": row["name"], "prompt": row["prompt"], "provider": row["provider"], "plan": self.runtime.json_value(row["plan"], {}), "validation": self.runtime.json_value(row["validation"], {}), "assetId": row["asset_id"], "version": row["version"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]} for row in payload["data"]]
            return self._json(payload)
        scene_history_match = re.fullmatch(r"/api/studio/scenes/([^/]+)", path)
        if scene_history_match:
            payload = self._page_table("studio_scene_versions", query, where="generation_id=? AND tenant_id=?", values=(scene_history_match.group(1), self.principal.tenant_id), order_by="version DESC")
            payload["data"] = [{"id": row["id"], "generationId": row["generation_id"], "version": row["version"], "command": row["command"], "operations": self.runtime.json_value(row["operations"], []), "plan": self.runtime.json_value(row["plan"], {}), "createdAt": row["created_at"]} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/studio/agent-runs":
            payload = self._page_table("agent_runs", query, default=50, select="id")
            payload["data"] = [self.runtime.serialize_agent_run(row["id"], self.runtime.OBJECT_STORE) for row in payload["data"]]
            return self._json(payload)
        agent_stream_match = re.fullmatch(r"/api/studio/agent-runs/([^/]+)/stream", path)
        if agent_stream_match:
            if not self._guard_owned("agent_runs", agent_stream_match.group(1)): return
            return self._stream_agent_run(agent_stream_match.group(1))
        agent_run_match = re.fullmatch(r"/api/studio/agent-runs/([^/]+)", path)
        if agent_run_match:
            if not self._guard_owned("agent_runs", agent_run_match.group(1)): return
            item = self.runtime.serialize_agent_run(agent_run_match.group(1), self.runtime.OBJECT_STORE)
            return self._json({"data": item}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        text3d_stream_match = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)/stream", path)
        if text3d_stream_match:
            if not self._guard_owned("text3d_jobs", text3d_stream_match.group(1)): return
            return self._stream_text3d_job(text3d_stream_match.group(1))
        text3d_match = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)", path)
        if text3d_match:
            if not self._guard_owned("text3d_jobs", text3d_match.group(1)): return
            item = self.runtime.get_text3d_job(text3d_match.group(1))
            return self._json({"data": item}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        model_job_match=re.fullmatch(r"/api/model-operation-jobs/([^/]+)",path)
        if model_job_match:
            with self.runtime.DB_LOCK,self.runtime.connect() as db:row=db.execute("SELECT * FROM model_operation_jobs WHERE id=? AND tenant_id=?",(model_job_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data":self.runtime.serialize_model_operation_job(row)},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        geometry_job_match=re.fullmatch(r"/api/geometry-jobs/([^/]+)",path)
        if geometry_job_match:
            with self.runtime.DB_LOCK,self.runtime.connect() as db: row=db.execute("SELECT * FROM geometry_jobs WHERE id=? AND tenant_id=?",(geometry_job_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data":self.runtime.serialize_geometry_job(row)},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        scene_agent_stream=re.fullmatch(r"/api/scene-agent-runs/([^/]+)/stream",path)
        if scene_agent_stream:
            if not self._guard_owned("scene_agent_runs",scene_agent_stream.group(1)): return
            return self._stream_scene_agent(scene_agent_stream.group(1))
        scene_agent_match=re.fullmatch(r"/api/scene-agent-runs/([^/]+)",path)
        if scene_agent_match:
            if not self._guard_owned("scene_agent_runs",scene_agent_match.group(1)): return
            item=self._scene_agent_payload(scene_agent_match.group(1));return self._json({"data":item},HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        scene_agents_match=re.fullmatch(r"/api/model-scenes/([^/]+)/agent-runs",path)
        if scene_agents_match:
            if not self._guard_owned("model_scenes",scene_agents_match.group(1)): return
            payload = self._page_table("scene_agent_runs", query, default=50, where="scene_id=? AND tenant_id=?", values=(scene_agents_match.group(1), self.principal.tenant_id), select="id")
            payload["data"] = [self._scene_agent_payload(row["id"]) for row in payload["data"]]
            return self._json(payload)
        if path == "/api/parameter-snapshots":
            payload = self._page_table("parameter_snapshots", query)
            payload["data"] = [{"id": row["id"], "name": row["name"], "runId": row["run_id"], "params": self.runtime.json_value(row["params"], {}), "createdAt": row["created_at"]} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/asset-projects":
            pagination = self.runtime.parse_pagination(query)
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                total = int(db.execute("SELECT COUNT(*) AS count FROM asset_projects WHERE tenant_id=?", (self.principal.tenant_id,)).fetchone()["count"])
                rows = db.execute("SELECT p.*,(SELECT COUNT(*) FROM model_assets a WHERE a.project_id=p.id AND a.tenant_id=p.tenant_id AND a.deleted_at IS NULL) AS asset_count FROM asset_projects p WHERE p.tenant_id=? ORDER BY p.name LIMIT ? OFFSET ?", (self.principal.tenant_id, pagination.page_size, pagination.offset)).fetchall()
            return self._json({"data": [{"id": row["id"], "name": row["name"], "description": row["description"], "assetCount": row["asset_count"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]} for row in rows], "pagination": self.runtime.page_meta(pagination, total)})
        if path == "/api/runs":
            pagination = self.runtime.parse_pagination(query)
            return self._json(self.runtime.run_service().list(self.principal.tenant_id, pagination, summary=(query.get("summary") or [""])[0] == "1", search=(query.get("q") or [""])[0]))
        if path == "/api/jobs":
            payload = self._page_table("jobs", query, default=50)
            payload["data"] = [{**row, "payload": self.runtime.json_value(row["payload"], {})} for row in payload["data"]]
            return self._json(payload)
        if path.startswith("/api/evaluation/"):
            service, tenant = self.runtime.EvaluationService(self.runtime.connect), self.principal.tenant_id
            pagination = self.runtime.parse_pagination(query, default=25, maximum=100)
            if path == "/api/evaluation/image-versions":
                return self._json(self.runtime.VisionDatasetService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK).list(tenant,pagination))
            image_version = re.fullmatch(r"/api/evaluation/image-versions/([^/]+)(?:/images/(\d+))?",path)
            if image_version:
                images = self.runtime.VisionDatasetService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK)
                if image_version.group(2) is not None: return self._binary(images.image(tenant,image_version.group(1),int(image_version.group(2))),"image/png")
                return self._json({"data":images.get(tenant,image_version.group(1))})
            if path == "/api/evaluation/experiments":
                return self._json(self.runtime.VisionExperimentService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK).list(tenant,pagination))
            experiment = re.fullmatch(r"/api/evaluation/experiments/([^/]+)",path)
            if experiment: return self._json({"data":self.runtime.VisionExperimentService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK).get(tenant,experiment.group(1))})
            synthesis_service = self.runtime.SynthesisService(self.runtime.connect, self.runtime.OBJECT_STORE, self.runtime.DB_LOCK)
            render_list = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)/renders", path)
            if render_list:
                return self._json(synthesis_service.list(tenant, pagination, render_list.group(1)))
            render_match = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)(/(frames|manifest|export))?", path)
            if render_match:
                job_id, action = render_match.group(1), render_match.group(3)
                if action == "export":
                    return self._binary(synthesis_service.package(tenant, job_id), "application/zip", job_id+".zip")
                if action == "manifest": return self._json({"data": synthesis_service.manifest(tenant, job_id)})
                if action == "frames": return self._json(synthesis_service.frames(tenant, job_id, pagination))
                return self._json({"data": synthesis_service.get(tenant, job_id)})
            render_artifact = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/frames/(\d+)/(image|mask|amodalMask)", path)
            if render_artifact:
                return self._binary(synthesis_service.artifact(tenant, render_artifact.group(1), int(render_artifact.group(2)), render_artifact.group(3)), "image/png")
            if path == "/api/evaluation/scenarios":
                return self._json(self.runtime.ScenarioService(self.runtime.connect, self.runtime.OBJECT_STORE, self.runtime.DB_LOCK).list(tenant, pagination, (query.get("reportId") or [None])[0]))
            scenario_match = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)(/(export|asset))?", path)
            if scenario_match:
                scenario_service = self.runtime.ScenarioService(self.runtime.connect, self.runtime.OBJECT_STORE, self.runtime.DB_LOCK)
                method = scenario_service.preview_asset if scenario_match.group(3) == "asset" else scenario_service.get
                return self._json({"data": method(tenant, scenario_match.group(1))})
            if path == "/api/evaluation/test-sets":
                return self._json(service.list_test_sets(tenant, pagination))
            if path == "/api/evaluation/reports":
                return self._json(service.list_evaluations(tenant, pagination, (query.get("testSetId") or [None])[0]))
            if path == "/api/evaluation/compare":
                return self._json({"data": service.compare(tenant, (query.get("baselineId") or [""])[0], (query.get("candidateId") or [""])[0])})
            match = re.fullmatch(r"/api/evaluation/test-sets/([^/]+)(/export)?", path)
            if match:
                method = service.export_test_set if match.group(2) else service.get_test_set
                return self._json({"data": method(tenant, match.group(1))})
            match = re.fullmatch(r"/api/evaluation/reports/([^/]+)(/cases)?", path)
            if match:
                if not match.group(2):
                    return self._json({"data": service.get_evaluation(tenant, match.group(1))})
                failures_only = (query.get("failuresOnly") or ["true"])[0]
                if failures_only not in {"true", "false"}:
                    raise self.runtime.ValidationError("failuresOnly must be true or false")
                return self._json(service.cases(tenant, match.group(1), pagination, failures_only=failures_only == "true",
                                               dimension=(query.get("dimension") or [None])[0], value=(query.get("value") or [None])[0]))
        if path == "/api/datasets":
            pagination = self.runtime.parse_pagination(query, default=50)
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                page = self.runtime.CollectionService.list(db, "datasets", pagination, values=(self.principal.tenant_id,))
            return self._json({"data": [{"id": row["id"], "name": row["name"], "format": row["format"], "storageFormat": row.get("storage_format", "json"), "schema": self.runtime.json_value(row["schema_json"], []), "schemaVersion": row.get("schema_version", 1), "currentVersionId": row.get("current_version_id"), "partitionBy": self.runtime.json_value(row.get("partition_by"), []), "rowCount": row["row_count"], "createdAt": row["created_at"], "updatedAt": row.get("updated_at") or row["created_at"]} for row in page.rows], "pagination": page.pagination})
        dataset_versions_match = re.fullmatch(r"/api/datasets/([^/]+)/versions", path)
        if dataset_versions_match:
            versions = self.runtime.DatasetCatalog(self.runtime.connect, self.runtime.OBJECT_STORE).versions(dataset_versions_match.group(1), self.principal.tenant_id)
            return self._json(self._page_values(versions, query, default=50))
        dataset_lineage_match = re.fullmatch(r"/api/datasets/([^/]+)/lineage", path)
        if dataset_lineage_match:
            return self._json({"data": self.runtime.DatasetCatalog(self.runtime.connect, self.runtime.OBJECT_STORE).lineage(dataset_lineage_match.group(1), self.principal.tenant_id)})
        if path == "/api/analysis/queries":
            payload = self._page_table("analysis_queries", query, default=50, order_by="created_at DESC")
            payload["data"] = [self.runtime.analysis_service().get(row["id"], self.principal.tenant_id, include_result=False) for row in payload["data"]]
            return self._json(payload)
        analysis_query_match = re.fullmatch(r"/api/analysis/queries/([^/]+)", path)
        if analysis_query_match:
            return self._json({"data": self.runtime.analysis_service().get(analysis_query_match.group(1), self.principal.tenant_id)})
        dataset_match = re.fullmatch(r"/api/datasets/([^/]+)", path)
        if dataset_match:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                row = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_match.group(1), self.principal.tenant_id)).fetchone()
                if not row:
                    return self._json({"error": "dataset not found"}, HTTPStatus.NOT_FOUND)
                keys = set(row.keys())
                return self._json({"data": {"id": row["id"], "name": row["name"], "format": row["format"], "storageFormat": row["storage_format"] if "storage_format" in keys else "json", "schema": self.runtime.json_value(row["schema_json"], []), "schemaVersion": row["schema_version"] if "schema_version" in keys else 1, "currentVersionId": row["current_version_id"] if "current_version_id" in keys else None, "partitionBy": self.runtime.json_value(row["partition_by"], []) if "partition_by" in keys else [], "rows": self.runtime.OBJECT_STORE.get_json(row["object_key"]), "rowCount": row["row_count"], "createdAt": row["created_at"], "updatedAt": row["updated_at"] if "updated_at" in keys else row["created_at"]}})
        if path == "/api/visualization-specs":
            payload = self._page_table("visualization_specs", query, order_by="updated_at DESC")
            payload["data"] = [{"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": self.runtime.json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]} for row in payload["data"]]
            return self._json(payload)
        spec_match = re.fullmatch(r"/api/visualization-specs/([^/]+)", path)
        share_match = re.fullmatch(r"/api/shared/([^/]+)", path)
        if spec_match or share_match:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                field, value = ("id", spec_match.group(1)) if spec_match else ("share_token", share_match.group(1))
                row = db.execute(f"SELECT * FROM visualization_specs WHERE {field}=? AND (tenant_id=? OR is_public=1)", (value, self.principal.tenant_id)).fetchone()
                if not row or (share_match and not row["is_public"]):
                    return self._json({"error": "visualization spec not found"}, HTTPStatus.NOT_FOUND)
                return self._json({"data": {"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": self.runtime.json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]}})
        if path == "/api/model-assets":
            pagination = self.runtime.parse_pagination(query, default=100)
            clauses = ["tenant_id=?"]; values: list = [self.principal.tenant_id]
            if query.get("q"):
                clauses.append("LOWER(name) LIKE ?"); values.append(f"%{query['q'][0].lower()}%")
            for parameter, column in (("projectId", "project_id"), ("stage", "stage"), ("folder", "folder")):
                if query.get(parameter): clauses.append(f"{column}=?"); values.append(query[parameter][0])
            if query.get("tag"):
                clauses.append("LOWER(tags) LIKE ?"); values.append(f"%{query['tag'][0].lower()}%")
            if query.get("archived", ["false"])[0].lower() != "true": clauses.append("archived_at IS NULL")
            if query.get("deleted", ["false"])[0].lower() != "true": clauses.append("deleted_at IS NULL")
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                total = int(db.execute(f"SELECT COUNT(*) AS count FROM model_assets WHERE {' AND '.join(clauses)}", values).fetchone()["count"])
                rows = db.execute(f"SELECT * FROM model_assets WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC,created_at DESC LIMIT ? OFFSET ?", (*values, pagination.page_size, pagination.offset)).fetchall()
            return self._json({"data": [self.runtime.serialize_model_asset(row) for row in rows], "pagination": self.runtime.page_meta(pagination, total)})
        if path == "/api/model-scenes":
            payload = self._page_table("model_scenes", query, order_by="updated_at DESC")
            payload["data"] = [self.runtime.serialize_model_scene(row) for row in payload["data"]]
            return self._json(payload)
        scene_versions_match=re.fullmatch(r"/api/model-scenes/([^/]+)/versions",path)
        scene_match=re.fullmatch(r"/api/model-scenes/([^/]+)",path)
        if scene_versions_match or scene_match:
            scene_id=(scene_versions_match or scene_match).group(1)
            with self.runtime.DB_LOCK,self.runtime.connect() as db: row=db.execute("SELECT * FROM model_scenes WHERE id=? AND tenant_id=?",(scene_id,self.principal.tenant_id)).fetchone()
            if not row: return self._json({"error":"model scene not found"},HTTPStatus.NOT_FOUND)
            return self._json({"data":self.runtime.serialize_model_scene(row,include_versions=bool(scene_versions_match))})
        asset_stream_match = re.fullmatch(r"/api/model-assets/([^/]+)/(stream-manifest|content)", path)
        if asset_stream_match:
            return self._stream_model_asset(asset_stream_match.group(1), asset_stream_match.group(2) == "stream-manifest")
        asset_match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
        if asset_match:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                row = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=?", (asset_match.group(1), self.principal.tenant_id)).fetchone()
                if not row:
                    return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
                include_content=query.get("content",["true"])[0].lower() not in {"0","false","no"}
                return self._json({"data": self.runtime.serialize_model_asset(row, include_content, True)})
        artifact_match = re.fullmatch(r"/api/artifacts/([^/]+)/content", path)
        if artifact_match:
            with self.runtime.DB_LOCK, self.runtime.connect() as db:
                item = db.execute("SELECT a.* FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.tenant_id=?", (artifact_match.group(1), self.principal.tenant_id)).fetchone()
                if not item:
                    return self._json({"error": "artifact not found"}, HTTPStatus.NOT_FOUND)
                object_key = item["object_key"] if "object_key" in item.keys() else None
                content = self.runtime.OBJECT_STORE.get_json(object_key) if object_key else self.runtime.json_value(item["content"], item["content"])
                return self._json({"data": content})
        stream_match = re.fullmatch(r"/api/runs/([^/]+)/stream", path)
        if stream_match:
            if not self._guard_owned("runs", stream_match.group(1)): return
            return self._stream(stream_match.group(1), query)
        changes_match = re.fullmatch(r"/api/runs/([^/]+)/changes", path)
        if changes_match:
            return self._json({"data": self.runtime.run_service().changes(changes_match.group(1), self.principal.tenant_id, int((query.get("after") or ["0"])[0]), int((query.get("limit") or ["100"])[0]))})
        timeline_match = re.fullmatch(r"/api/runs/([^/]+)/timeline", path)
        if timeline_match:
            if not self._guard_owned("runs", timeline_match.group(1)): return
            return self._run_timeline(timeline_match.group(1))
        lineage_match = re.fullmatch(r"/api/runs/([^/]+)/lineage", path)
        if lineage_match:
            if not self._guard_owned("runs", lineage_match.group(1)): return
            with self.runtime.DB_LOCK,self.runtime.connect() as db: row=db.execute("SELECT * FROM training_lineage WHERE run_id=? AND tenant_id=?",(lineage_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data": {**dict(row),"environment":self.runtime.json_value(row["environment"],{})} if row else None},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        run_match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if run_match:
            if not self._guard_owned("runs", run_match.group(1)): return
            run = self.runtime.run_service().get(run_match.group(1), self.principal.tenant_id)
            return self._json({"data": run}, HTTPStatus.OK if run else HTTPStatus.NOT_FOUND)
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
