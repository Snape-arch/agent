"""Mutations adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse
import json
import re


class MutationsHandler:
    runtime: HandlerRuntime

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/auth/bootstrap":
                principal, token = self.runtime.bootstrap(str(body.get("email") or ""), str(body.get("password") or ""), str(body.get("tenantName") or "ClawVision")); return self._json({"data": {"token": token, "userId": principal.user_id, "tenantId": principal.tenant_id, "role": principal.role}}, HTTPStatus.CREATED)
            if path == "/api/auth/login":
                principal, token = self.runtime.login(str(body.get("email") or ""), str(body.get("password") or "")); return self._json({"data": {"token": token, "userId": principal.user_id, "tenantId": principal.tenant_id, "role": principal.role}})
            if not self._authorize(path, write=True, admin=path in {"/api/auth/tokens", "/api/credential-refs"}): return
            if not self._guard_write_path(path, body): return
            if path == "/api/telemetry/3d":
                return self._save_three_telemetry(body)
            if path == "/api/auth/tokens": return self._json({"data": {"token": self.runtime.issue_token(self.principal, str(body.get("name") or "API token"), body.get("scopes") if isinstance(body.get("scopes"), list) else None, int(body.get("expiresHours") or 720))}}, HTTPStatus.CREATED)
            if path == "/api/auth/members": return self._json({"data": self.runtime.create_member(self.principal, str(body.get("email") or ""), str(body.get("password") or ""), str(body.get("role") or "viewer"))}, HTTPStatus.CREATED)
            if path == "/api/credential-refs":
                item_id = self.runtime.save_credential(self.principal, str(body.get("provider") or ""), str(body.get("name") or "credential"), str(body.get("secret") or ""))
                return self._json({"data": {"id": item_id, "provider": body.get("provider"), "name": body.get("name")}}, HTTPStatus.CREATED)
            if path == "/api/runs":
                return self._create_run(body)
            if path == "/api/evaluation/image-datasets":
                return self._json({"data":self.runtime.VisionDatasetService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK).create_real(self.principal.tenant_id,body)},HTTPStatus.CREATED)
            register_synthetic = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/dataset-version",path)
            if register_synthetic:
                return self._json({"data":self.runtime.VisionDatasetService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK).from_synthesis(self.principal.tenant_id,register_synthetic.group(1),body)},HTTPStatus.CREATED)
            experiment_action = re.fullmatch(r"/api/evaluation/experiments/([^/]+)/(cancel|retry)",path)
            if path == "/api/evaluation/experiments" or experiment_action:
                service = self.runtime.VisionExperimentService(self.runtime.connect,self.runtime.OBJECT_STORE,self.runtime.DB_LOCK)
                result = service.action(self.principal.tenant_id,experiment_action.group(1),experiment_action.group(2)) if experiment_action else service.create(self.principal.tenant_id,body)
                if result["status"] == "queued":
                    with self.runtime.connect() as db: task = self.runtime.serialize_task(db.execute("SELECT * FROM durable_tasks WHERE id=?",(result["taskId"],)).fetchone())
                    self.runtime.submit_synthesis(task)
                return self._json({"data":result},HTTPStatus.ACCEPTED)
            synthesis_create = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)/renders", path)
            synthesis_action = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/(cancel|retry)", path)
            if synthesis_create or synthesis_action:
                service = self.runtime.SynthesisService(self.runtime.connect, self.runtime.OBJECT_STORE, self.runtime.DB_LOCK)
                tenant = self.principal.tenant_id
                if synthesis_create:
                    result = service.create(tenant, synthesis_create.group(1), body)
                else:
                    result = service.action(tenant, synthesis_action.group(1), synthesis_action.group(2))
                if result["status"] == "queued":
                    with self.runtime.connect() as db: task = self.runtime.serialize_task(db.execute("SELECT * FROM durable_tasks WHERE id=?", (result["taskId"],)).fetchone())
                    self.runtime.submit_synthesis(task)
                return self._json({"data": result}, HTTPStatus.ACCEPTED)
            if path == "/api/evaluation/scenarios":
                return self._json({"data": self.runtime.ScenarioService(self.runtime.connect, self.runtime.OBJECT_STORE, self.runtime.DB_LOCK).create(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/evaluation/test-sets":
                return self._json({"data": self.runtime.EvaluationService(self.runtime.connect).create_test_set(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/evaluation/reports":
                return self._json({"data": self.runtime.EvaluationService(self.runtime.connect).create_evaluation(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/jobs":
                return self._create_job(body)
            task_cancel = re.fullmatch(r"/api/tasks/([^/]+)/cancel", path)
            if task_cancel:
                return self._json({"ok": self.runtime.cancel_task(task_cancel.group(1), self.principal.tenant_id)}, HTTPStatus.ACCEPTED)
            training_cancel = re.fullmatch(r"/api/training-jobs/([^/]+)/cancel", path)
            if training_cancel:
                training_id = training_cancel.group(1)
                with self.runtime.DB_LOCK, self.runtime.connect() as db:
                    db.execute("UPDATE training_jobs SET cancel_requested=1,stage='cancelling',updated_at=? WHERE id=? AND tenant_id=?", (self.runtime.now_iso(), training_id,self.principal.tenant_id))
                    task_row=db.execute("SELECT id FROM durable_tasks WHERE resource_id=? AND tenant_id=? AND kind='training'",(training_id,self.principal.tenant_id)).fetchone()
                if task_row: self.runtime.cancel_task(task_row["id"],self.principal.tenant_id)
                self.runtime.cancel_training_process(training_id)
                return self._json({"data": {"id": training_id, "cancelRequested": True}}, HTTPStatus.ACCEPTED)
            if path == "/api/datasets":
                return self._create_dataset(body)
            dataset_version = re.fullmatch(r"/api/datasets/([^/]+)/versions", path)
            if dataset_version:
                return self._create_dataset(body, dataset_version.group(1))
            dataset_query = re.fullmatch(r"/api/datasets/([^/]+)/query", path)
            if dataset_query:
                return self._query_dataset(dataset_query.group(1), body)
            if path == "/api/analysis/query":
                return self._json({"data": self.runtime.analysis_service().execute(self.principal.tenant_id, body)})
            if path == "/api/analysis/queries":
                return self._json({"data": self.runtime.analysis_service().submit(self.principal.tenant_id, body)}, HTTPStatus.ACCEPTED)
            analysis_cancel = re.fullmatch(r"/api/analysis/queries/([^/]+)/cancel", path)
            if analysis_cancel:
                return self._json({"data": self.runtime.analysis_service().cancel(analysis_cancel.group(1), self.principal.tenant_id)}, HTTPStatus.ACCEPTED)
            if path == "/api/visualization-specs":
                return self._save_visualization_spec(body)
            if path == "/api/model-assets":
                return self._create_model_asset(body)
            if path == "/api/asset-projects":
                return self._create_asset_project(body)
            if path == "/api/model-assets/batch":
                return self._batch_update_assets(body)
            if path == "/api/model-assets/garbage-collect":
                return self._garbage_collect_assets(body)
            run_asset_link = re.fullmatch(r"/api/runs/([^/]+)/assets", path)
            if run_asset_link:
                return self._link_run_asset(run_asset_link.group(1), body)
            asset_catalog_action = re.fullmatch(r"/api/model-assets/([^/]+)/(archive|restore|components|releases)", path)
            if asset_catalog_action:
                asset_id, action = asset_catalog_action.groups()
                if action == "archive": return self._set_asset_archive(asset_id, True)
                if action == "restore": return self._set_asset_archive(asset_id, False)
                if action == "components": return self._create_asset_component(asset_id, body)
                return self._create_asset_release(asset_id, body)
            asset_geometry_job=re.fullmatch(r"/api/model-assets/([^/]+)/geometry-jobs",path)
            if asset_geometry_job:return self._create_geometry_job(None,asset_geometry_job.group(1),body)
            asset_scene_import=re.fullmatch(r"/api/model-assets/([^/]+)/scene",path)
            if asset_scene_import:
                return self._import_model_scene(asset_scene_import.group(1),body)
            scene_async=re.fullmatch(r"/api/model-scenes/([^/]+)/operations/async",path)
            if scene_async:return self._queue_model_operations(scene_async.group(1),body)
            model_job_cancel=re.fullmatch(r"/api/model-operation-jobs/([^/]+)/cancel",path)
            if model_job_cancel:return self._cancel_model_operation(model_job_cancel.group(1))
            geometry_cancel=re.fullmatch(r"/api/geometry-jobs/([^/]+)/cancel",path)
            if geometry_cancel:return self._cancel_geometry_job(geometry_cancel.group(1))
            scene_agent_create=re.fullmatch(r"/api/model-scenes/([^/]+)/agent-runs",path)
            if scene_agent_create:return self._create_scene_agent(scene_agent_create.group(1),body)
            scene_agent_action=re.fullmatch(r"/api/scene-agent-runs/([^/]+)/(confirm|apply|reject|cancel)",path)
            if scene_agent_action:
                agent_id,action=scene_agent_action.groups()
                if action=="confirm":return self._confirm_scene_agent(agent_id)
                if action=="apply":return self._apply_scene_agent(agent_id)
                return self._stop_scene_agent(agent_id,action)
            scene_geometry_job=re.fullmatch(r"/api/model-scenes/([^/]+)/geometry-jobs",path)
            if scene_geometry_job:return self._create_geometry_job(scene_geometry_job.group(1),None,body)
            scene_action=re.fullmatch(r"/api/model-scenes/([^/]+)/(command|preview|operations|restore|repair|export)",path)
            if scene_action:
                scene_id,action=scene_action.groups()
                if action=="command": return self._model_scene_command(scene_id,body)
                if action=="preview": return self._preview_model_scene(scene_id,body)
                if action=="operations": return self._apply_model_scene(scene_id,body)
                if action=="restore": return self._restore_model_scene(scene_id,body)
                if action=="repair": return self._repair_model_scene(scene_id,body)
                return self._export_model_scene(scene_id)
            if path == "/api/ai/interpret":
                return self._interpret_ai(body)
            if path == "/api/studio/generations":
                return self._save_studio_generation(body)
            if path == "/api/studio/scene-command":
                plan = body.get("plan")
                if not isinstance(plan, dict): raise ValueError("plan must be an object")
                return self._json({"data": self.runtime.interpret_scene_command(str(body.get("command") or ""), plan)}, HTTPStatus.CREATED)
            if path == "/api/studio/scenes/apply":
                return self._apply_scene_operations(body)
            if path == "/api/studio/agent-runs":
                return self._create_agent_pipeline(body)
            if path == "/api/studio/text-to-3d":
                return self._create_text3d_worker_job(body)
            agent_cancel = re.fullmatch(r"/api/studio/agent-runs/([^/]+)/cancel", path)
            if agent_cancel:
                item=self.runtime.cancel_agent_run(agent_cancel.group(1)); return self._json({"data":item},HTTPStatus.ACCEPTED if item else HTTPStatus.NOT_FOUND)
            text3d_cancel = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)/cancel", path)
            if text3d_cancel:
                item=self.runtime.cancel_text3d_job(text3d_cancel.group(1)); return self._json({"data":item},HTTPStatus.ACCEPTED if item else HTTPStatus.NOT_FOUND)
            if path == "/api/studio/validate":
                return self._json({"data": self.runtime.validate_plan(body.get("plan") if isinstance(body.get("plan"), dict) else {})})
            if path == "/api/studio/mesh":
                return self._compile_studio_mesh(body)
            if path == "/api/studio/export":
                return self._export_studio_asset(body)
            if path == "/api/parameter-snapshots":
                return self._save_parameter_snapshot(body)
            feedback_match = re.fullmatch(r"/api/studio/generations/([^/]+)/feedback", path)
            if feedback_match:
                return self._save_studio_feedback(feedback_match.group(1), body)
            match = re.fullmatch(r"/api/runs/([^/]+)/(batch|params|metrics|events|artifacts|finish|fail|stop|resume)", path)
            lineage_match = re.fullmatch(r"/api/runs/([^/]+)/lineage", path)
            if lineage_match: return self._save_training_lineage(lineage_match.group(1), body)
            if not match:
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            run_id, action = match.groups()
            if action == "batch":
                return self._batch(run_id, body)
            if action == "params":
                return self._log_params(run_id, body)
            if action == "metrics":
                return self._log_metrics(run_id, body)
            if action == "events":
                return self._log_event(run_id, body)
            if action == "artifacts":
                return self._log_artifact(run_id, body)
            if action == "resume":
                return self._resume_run(run_id, body)
            status = "completed" if action == "finish" else "stopped" if action == "stop" else "failed"
            return self._set_status(run_id, status, body)
        except self.runtime.ApplicationError as error:
            self._json({"error": error.message, "code": error.code, "detail": error.detail}, error.status)
        except PermissionError as error:
            self._json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            if self.runtime.is_integrity_error(error):
                return self._json({"error": str(error)}, HTTPStatus.CONFLICT)
            self._json({"error": str(error)}, HTTPStatus.BAD_GATEWAY if path == "/api/ai/interpret" else HTTPStatus.INTERNAL_SERVER_ERROR)


    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if not self._authorize(path, write=True): return
            body = self._body()
            if not self._guard_write_path(path, body): return
            match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
            if match: return self._update_model_asset(match.group(1), body)
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)


    def do_DELETE(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path); path = parsed_url.path; query = parse_qs(parsed_url.query)
        try:
            if not self._authorize(path, write=True, admin=query.get("purge", ["false"])[0].lower() == "true"): return
            token_match = re.fullmatch(r"/api/auth/tokens/([^/]+)", path)
            if token_match: return self._json({"ok": self.runtime.revoke_token(self.principal, token_match.group(1))})
            match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
            if not match: return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return self._delete_model_asset(match.group(1), query.get("purge", ["false"])[0].lower() == "true")
        except Exception as error:
            if self.runtime.is_integrity_error(error): return self._json({"error": str(error)}, HTTPStatus.CONFLICT)
            self._json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
