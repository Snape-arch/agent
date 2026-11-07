"""Geometry adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import json
import re
import uuid


class GeometryHandler:
    runtime: HandlerRuntime

    def _preview_professional_operation(self,operation: dict) -> dict | None:
        kind=str(operation.get("kind") or "");targets=operation.get("targetIds") if isinstance(operation.get("targetIds"),list) else []
        mapping={"exact-boolean":("boolean",{"operator":operation.get("operator","union"),"resolution":20}),"fillet":("bevel",{"amount":operation.get("radius",.01)}),"chamfer":("chamfer",{"amount":operation.get("amount",.01)}),"retopology":("remesh",{"targetFaces":operation.get("targetFaces",5000)}),"repair":("normal-repair",{}),"uv-unwrap":("normal-repair",{})}
        if kind not in mapping:return None
        modifier,payload=mapping[kind];return {"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":modifier,**payload},"enabled":True}


    def _create_geometry_job(self,scene_id: str|None,asset_id: str|None,body: dict) -> None:
        self.runtime.check_task_quota(self.principal)
        provider=str(body.get("provider") or "builtin-voxel");catalog={item["id"]:item for item in self.runtime.geometry_provider_catalog()}
        if provider not in catalog:raise ValueError("unsupported geometry provider")
        if provider!="builtin-voxel" and not catalog[provider]["configured"]:raise ValueError(f"geometry provider {provider} is not configured")
        scene=self._scene_row(scene_id) if scene_id else None;source_asset_id=str(asset_id or scene["current_asset_id"]);operation=body.get("operation") if isinstance(body.get("operation"),dict) else {"kind":"convert","outputFormat":body.get("outputFormat","glb")}
        job_id="geometry_"+uuid.uuid4().hex[:12];created=self.runtime.now_iso();priority=max(0,min(100,int(body.get("priority") or 50)));timeout=max(30,min(7200,int(body.get("timeoutSeconds") or 900)))
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            if not db.execute("SELECT id FROM model_assets WHERE id=?",(source_asset_id,)).fetchone():return self._json({"error":"source model asset not found"},HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO geometry_jobs(id,scene_id,source_asset_id,provider,operation,status,progress,stage,priority,preview_asset_id,result_asset_id,checkpoint_key,result,error,cancel_requested,timeout_seconds,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,scene_id,source_asset_id,provider,json.dumps(operation,ensure_ascii=False),"queued",0,"queued",priority,None,None,body.get("checkpointKey"),None,None,0,timeout,created,created,self.principal.tenant_id))
        task=self.runtime.enqueue_task(self.principal.tenant_id,"geometry",job_id,{"provider":provider},f"geometry:{job_id}",priority=priority)
        self.runtime.submit_durable(task,self._execute_geometry_job,job_id);self._json({"data":self._geometry_job(job_id)},HTTPStatus.ACCEPTED)


    def _geometry_job(self,job_id: str) -> dict|None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:row=db.execute("SELECT * FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
        return self.runtime.serialize_geometry_job(row)


    def _geometry_cancelled(self,job_id: str) -> bool:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:row=db.execute("SELECT cancel_requested FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
        return not row or bool(row["cancel_requested"])


    def _execute_geometry_job(self,job_id: str) -> None:
        if not self.runtime.GEOMETRY_LIMIT.acquire(timeout=30):
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status='failed',error='geometry concurrency timeout',updated_at=? WHERE id=?",(self.runtime.now_iso(),job_id))
            return
        try:
            with self.runtime.DB_LOCK,self.runtime.connect() as db:
                job=db.execute("SELECT * FROM geometry_jobs WHERE id=?",(job_id,)).fetchone();asset=db.execute("SELECT * FROM model_assets WHERE id=?",(job["source_asset_id"],)).fetchone() if job else None
            if not job or not asset or job["cancel_requested"]:return
            operation=self.runtime.json_value(job["operation"],{});scene=self._scene_row(job["scene_id"]) if job["scene_id"] else None
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status='previewing',progress=5,stage='low-resolution-preview',updated_at=? WHERE id=?",(self.runtime.now_iso(),job_id))
            preview_operation=self._preview_professional_operation(operation)
            if scene and preview_operation:
                preview_rendered=self._render_model_scene(scene,self.runtime.json_value(scene["operations"],[])+[preview_operation]);preview_asset=self.runtime.store_model_asset("preview-"+preview_rendered["name"],preview_rendered["format"],preview_rendered["payload"],{"source":"geometry-low-resolution-preview","geometryJobId":job_id,"assetStage":"preview"},preview_rendered["resources"],self.principal.tenant_id)
                with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET preview_asset_id=?,progress=20,updated_at=? WHERE id=?",(preview_asset["id"],self.runtime.now_iso(),job_id))
            if job["provider"]=="builtin-voxel":
                if not scene or not preview_operation:raise ValueError("builtin geometry provider requires an editable scene operation")
                result=self._persist_model_scene_version(scene,self.runtime.json_value(scene["operations"],[])+[preview_operation],f"geometry worker: {operation.get('kind')}",lambda:self._geometry_cancelled(job_id));asset_id=result["currentAssetId"]
                with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status='completed',progress=100,stage='completed',result_asset_id=?,result=?,updated_at=? WHERE id=?",(asset_id,json.dumps(result,ensure_ascii=False),self.runtime.now_iso(),job_id))
                return
            stored=self.runtime.OBJECT_STORE.get_json(asset["object_key"]);request={"jobId":job_id,"operation":operation,"source":{"name":asset["name"],"format":asset["format"],"content":stored["base64"],"resources":stored.get("resources",[])},"outputFormat":operation.get("outputFormat","glb"),"checkpointKey":job["checkpoint_key"]}
            def progress(value,stage,checkpoint=None):
                key=None
                if checkpoint:key=self.runtime.OBJECT_STORE.put_json(f"geometry/{job_id}/checkpoint-{max(0,min(100,value))}.json",checkpoint)
                with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status='provider-running',progress=?,stage=?,checkpoint_key=COALESCE(?,checkpoint_key),updated_at=? WHERE id=?",(max(20,min(94,value)),stage[:120],key,self.runtime.now_iso(),job_id))
            result=self.runtime.run_geometry_provider(job["provider"],request,int(job["timeout_seconds"]),progress,lambda:self._geometry_cancelled(job_id))
            if self._geometry_cancelled(job_id):raise RuntimeError("cancelled")
            output=result.content;output_format=result.format
            if scene and output_format in {"obj","stl","ply"}:
                document,binary=self.runtime.canonicalize_mesh_asset(output,output_format,asset["name"]);output=self.runtime.pack_glb(document,binary);output_format="glb"
            scene_result=None;manifest=None;quality=None
            if scene:
                document,binary=self.runtime.parse_asset(output,output_format);manifest=self.runtime.scene_manifest(document);quality=self.runtime.quality_report(output,manifest,70) if output_format=="glb" else {"format":output_format,"score":85,"threshold":70,"passed":True,"issues":[],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
                if not self.runtime.quality_accepts(quality,self.runtime.json_value(scene["quality"],{})):
                    raise RuntimeError(f"professional geometry quality gate rejected output: {quality.get('issues') or 'invalid mesh'}; source scene is unchanged")
            final=self.runtime.store_model_asset(re.sub(r"\.(step|stp|iges|igs|ply|obj|stl|gltf|glb)$",f".{output_format}",asset["name"],flags=re.I),output_format,output,{"source":"professional-geometry-worker","geometryJobId":job_id,"provider":job["provider"],"operation":operation,"stats":result.stats,"assetStage":"release"},tenant_id=self.principal.tenant_id)
            if scene:
                version=int(scene["version"])+1;operations=self.runtime.json_value(scene["operations"],[])+[{"id":"professional_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":operation.get("targetIds",[]),"payload":{**operation,"provider":job["provider"],"kernel":"professional"},"enabled":True}];created=self.runtime.now_iso()
                with self.runtime.DB_LOCK,self.runtime.connect() as db:
                    db.execute("UPDATE model_scenes SET current_asset_id=?,version=?,operations=?,scene_json=?,quality=?,updated_at=? WHERE id=?",(final["id"],version,json.dumps(operations,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created,scene["id"]));db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",("msv_"+uuid.uuid4().hex[:12],scene["id"],version,final["id"],json.dumps(operations,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created));updated=db.execute("SELECT * FROM model_scenes WHERE id=?",(scene["id"],)).fetchone()
                scene_result=self.runtime.serialize_model_scene(updated,True)
            payload={"asset":final,"scene":scene_result,"stats":result.stats}
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status='completed',progress=100,stage='high-quality-replaced',result_asset_id=?,result=?,updated_at=? WHERE id=?",(final["id"],json.dumps(payload,ensure_ascii=False),self.runtime.now_iso(),job_id))
        except Exception as error:
            state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE geometry_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(state,state,str(error)[:2000],self.runtime.now_iso(),job_id))
        finally:self.runtime.GEOMETRY_LIMIT.release()


    def _cancel_geometry_job(self,job_id: str) -> None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            row=db.execute("SELECT status FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return self._json({"error":"geometry job not found"},HTTPStatus.NOT_FOUND)
            status="cancelled" if row["status"]=="queued" else row["status"];db.execute("UPDATE geometry_jobs SET cancel_requested=1,status=?,stage='cancel-requested',updated_at=? WHERE id=?",(status,self.runtime.now_iso(),job_id))
        self._json({"data":self._geometry_job(job_id)},HTTPStatus.ACCEPTED)


    def _queue_model_operations(self,scene_id: str,body: dict) -> None:
        self.runtime.check_task_quota(self.principal)
        row=self._scene_row(scene_id);additions=body.get("operations") if isinstance(body.get("operations"),list) else []
        if not additions or len(additions)>50:raise ValueError("operations must contain 1 to 50 items")
        operations=self.runtime.json_value(row["operations"],[])+additions
        if len(operations)>500:raise ValueError("scene operation stack exceeds 500 items")
        job_id="meshjob_"+uuid.uuid4().hex[:12];created=self.runtime.now_iso();payload={"operations":operations,"command":str(body.get("command") or "background mesh operation")}
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("INSERT INTO model_operation_jobs(id,scene_id,status,progress,stage,operations,result,error,cancel_requested,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,scene_id,"queued",0,"queued",json.dumps(payload,ensure_ascii=False),None,None,0,created,created,self.principal.tenant_id))
        task=self.runtime.enqueue_task(self.principal.tenant_id,"model-operation",job_id,payload,f"model-operation:{job_id}")
        self.runtime.submit_durable(task,self._execute_model_operation,job_id);self._json({"data":{"id":job_id,"sceneId":scene_id,"status":"queued","progress":0,"stage":"queued","operations":additions,"cancelRequested":False,"createdAt":created,"updatedAt":created}},HTTPStatus.ACCEPTED)


    def _execute_model_operation(self,job_id: str) -> None:
        try:
            with self.runtime.DB_LOCK,self.runtime.connect() as db:
                job=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
                if not job or job["cancel_requested"]:return
                db.execute("UPDATE model_operation_jobs SET status='running',progress=20,stage='voxelizing / topology',updated_at=? WHERE id=?",(self.runtime.now_iso(),job_id))
            payload=self.runtime.json_value(job["operations"],{});row=self._scene_row(job["scene_id"])
            def cancelled():
                with self.runtime.DB_LOCK,self.runtime.connect() as db:item=db.execute("SELECT cancel_requested FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
                return not item or bool(item["cancel_requested"])
            result=self._persist_model_scene_version(row,payload.get("operations",[]),str(payload.get("command") or "background mesh operation"),cancelled)
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE model_operation_jobs SET status='completed',progress=100,stage='completed',result=?,updated_at=? WHERE id=?",(json.dumps(result,ensure_ascii=False),self.runtime.now_iso(),job_id))
        except Exception as error:
            cancelled_state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE model_operation_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(cancelled_state,cancelled_state,str(error)[:1000],self.runtime.now_iso(),job_id))


    def _cancel_model_operation(self,job_id: str) -> None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            row=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return self._json({"error":"model operation job not found"},HTTPStatus.NOT_FOUND)
            status="cancelled" if row["status"]=="queued" else row["status"];db.execute("UPDATE model_operation_jobs SET cancel_requested=1,status=?,stage=?,updated_at=? WHERE id=?",(status,"cancel requested" if status=="running" else status,self.runtime.now_iso(),job_id));updated=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
        self._json({"data":self.runtime.serialize_model_operation_job(updated)},HTTPStatus.ACCEPTED)
