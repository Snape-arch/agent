"""Scene agents adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import base64
import json
import uuid


class SceneAgentsHandler:
    runtime: HandlerRuntime

    def _create_scene_agent(self,scene_id: str,body: dict) -> None:
        self.runtime.check_task_quota(self.principal)
        row=self._scene_row(scene_id);command=str(body.get("command") or "").strip()
        if not command or len(command)>2000:raise ValueError("command must contain 1 to 2000 characters")
        run_id="sceneagent_"+uuid.uuid4().hex[:12];created=self.runtime.now_iso();provider=str(body.get("provider") or "local-semantic");model=str(body.get("model") or "scene-graph-v1");max_cycles=max(1,min(4,int(body.get("maxCycles") or 2)))
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("INSERT INTO scene_agent_runs(id,scene_id,command,provider,model,status,progress,stage,base_version,operations,analysis,preview,result,error,risk_level,estimated_cost,estimated_seconds,quality_cycles,max_cycles,cancel_requested,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,scene_id,command,provider,model,"queued",0,"queued",row["version"],"[]","{}",None,None,None,"low",0,0,0,max_cycles,0,created,created,self.principal.tenant_id))
        task=self.runtime.enqueue_task(self.principal.tenant_id,"scene-agent",run_id,{"sceneId":scene_id},f"scene-agent:{run_id}")
        self.runtime.submit_durable(task,self._execute_scene_agent,run_id,False);self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.ACCEPTED)


    def _scene_agent_cancelled(self,run_id: str) -> bool:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:row=db.execute("SELECT cancel_requested FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        return not row or bool(row["cancel_requested"])


    def _execute_scene_agent(self,run_id: str,confirmed: bool=False) -> None:
        acquired=self.runtime.SCENE_AGENT_LIMIT.acquire(timeout=10)
        if not acquired:
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='failed',error='scene agent concurrency timeout',updated_at=? WHERE id=?",(self.runtime.now_iso(),run_id))
            return
        try:
            with self.runtime.DB_LOCK,self.runtime.connect() as db:run=db.execute("SELECT * FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
            if not run or run["cancel_requested"]:return
            scene=self._scene_row(run["scene_id"]);manifest=self.runtime.json_value(scene["scene_json"],{})
            understanding=self.runtime.understand_scene(manifest);self.runtime.record_decision(run_id,"understanding","accept","scene graph roles and topology summarized",understanding)
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='understanding',progress=18,stage='structure-understanding',analysis=?,updated_at=? WHERE id=?",(json.dumps({"understanding":understanding},ensure_ascii=False),self.runtime.now_iso(),run_id))
            if self._scene_agent_cancelled(run_id):raise RuntimeError("cancelled")
            planned=self.runtime.interpret_asset_command(run["command"],manifest);operations=planned["operations"];self.runtime.record_decision(run_id,"planning","accept",planned.get("explanation","semantic operations planned"),{"operations":operations,"affectedNodeIds":planned.get("affectedNodeIds",[])})
            risk=self.runtime.assess_operations(operations,understanding,manifest);analysis={"understanding":understanding,"plan":{"explanation":planned.get("explanation"),"affectedNodeIds":planned.get("affectedNodeIds",[])},"risk":risk};self.runtime.record_decision(run_id,"risk","confirm-required" if risk["requiresConfirmation"] else "continue",f"risk {risk['level']} · score {risk['score']}",risk)
            status="awaiting-confirmation" if risk["requiresConfirmation"] and not confirmed else "planning"
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,progress=?,stage=?,operations=?,analysis=?,risk_level=?,estimated_cost=?,estimated_seconds=?,updated_at=? WHERE id=?",(status,35,"risk-gate" if status=="awaiting-confirmation" else "previewing",json.dumps(operations,ensure_ascii=False),json.dumps(analysis,ensure_ascii=False),risk["level"],risk["estimatedCost"],risk["estimatedSeconds"],self.runtime.now_iso(),run_id))
            if status=="awaiting-confirmation":return
            cycles=0;targets=planned.get("affectedNodeIds",[]) or [node.get("id") for node in manifest.get("nodes",[]) if node.get("meshIndex") is not None]
            while cycles<int(run["max_cycles"]):
                if self._scene_agent_cancelled(run_id):raise RuntimeError("cancelled")
                cycles+=1
                with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='previewing',progress=?,stage=?,quality_cycles=?,updated_at=? WHERE id=?",(45+cycles*15,f"preview-cycle-{cycles}",cycles,self.runtime.now_iso(),run_id))
                rendered=self._render_model_scene(scene,operations);stored={"name":rendered["name"],"format":rendered["format"],"base64":base64.b64encode(rendered["payload"]).decode("ascii"),"resources":rendered["resources"]};key=self.runtime.OBJECT_STORE.put_json(f"studio/scene-agents/{run_id}/preview-{cycles}.json",stored)
                accepted=self.runtime.quality_accepts(rendered["quality"],self.runtime.json_value(scene["quality"],{}));preview={"objectKey":key,"quality":rendered["quality"],"scene":rendered["manifest"],"cycle":cycles,"modifierStats":rendered["modifierStats"]};self.runtime.record_decision(run_id,"quality","accept" if accepted else "return-to-repair",f"quality score {rendered['quality'].get('score')} · {'absolute or non-regression gate passed' if accepted else 'regression detected'}",{"cycle":cycles,"quality":rendered["quality"],"baseline":self.runtime.json_value(scene["quality"],{}),"artifactKey":key})
                with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET preview=?,progress=?,stage='quality-check',updated_at=? WHERE id=?",(json.dumps(preview,ensure_ascii=False),70+cycles*8,self.runtime.now_iso(),run_id))
                if accepted:
                    result={"operations":operations,"quality":rendered["quality"],"scene":rendered["manifest"],"affectedNodeIds":targets}
                    with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='ready',progress=100,stage='ready-to-apply',operations=?,result=?,updated_at=? WHERE id=?",(json.dumps(operations,ensure_ascii=False),json.dumps(result,ensure_ascii=False),self.runtime.now_iso(),run_id))
                    return
                repair={"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"normal-repair","fillHoles":True,"removeFragments":True},"enabled":True};operations=operations+[repair]
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='failed',stage='quality-rejected',error='Quality Agent rejected all repair cycles; source scene is unchanged',updated_at=? WHERE id=?",(self.runtime.now_iso(),run_id))
        except Exception as error:
            state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(state,state,str(error)[:2000],self.runtime.now_iso(),run_id))
        finally:self.runtime.SCENE_AGENT_LIMIT.release()


    def _confirm_scene_agent(self,run_id: str) -> None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:row=db.execute("SELECT status FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        if not row:return self._json({"error":"scene agent run not found"},HTTPStatus.NOT_FOUND)
        if row["status"]!="awaiting-confirmation":raise ValueError("scene agent is not awaiting confirmation")
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='planning',progress=36,stage='confirmed-queued',updated_at=? WHERE id=?",(self.runtime.now_iso(),run_id))
        self.runtime.EXECUTOR.submit(self._execute_scene_agent,run_id,True);self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.ACCEPTED)


    def _apply_scene_agent(self,run_id: str) -> None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db:run=db.execute("SELECT * FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        if not run:return self._json({"error":"scene agent run not found"},HTTPStatus.NOT_FOUND)
        if run["status"]!="ready":raise ValueError("scene agent must pass quality before apply")
        scene=self._scene_row(run["scene_id"])
        if int(scene["version"])!=int(run["base_version"]):
            with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='stale',stage='version-conflict',error='scene changed after Agent preview; re-run planning',updated_at=? WHERE id=?",(self.runtime.now_iso(),run_id))
            return self._json({"error":"scene changed after Agent preview; re-run planning"},HTTPStatus.CONFLICT)
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='applying',stage='atomic-apply',updated_at=? WHERE id=?",(self.runtime.now_iso(),run_id))
        operations=self.runtime.json_value(run["operations"],[]);result=self._persist_model_scene_version(scene,self.runtime.json_value(scene["operations"],[])+operations,run["command"])
        self.runtime.record_decision(run_id,"apply","commit","quality-approved operations committed atomically",{"sceneVersion":result["version"],"assetId":result["currentAssetId"]})
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status='completed',progress=100,stage='completed',result=?,updated_at=? WHERE id=?",(json.dumps(result,ensure_ascii=False),self.runtime.now_iso(),run_id))
        self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.CREATED)


    def _stop_scene_agent(self,run_id: str,action: str) -> None:
        status="rejected" if action=="reject" else "cancelled";created=self.runtime.now_iso()
        with self.runtime.DB_LOCK,self.runtime.connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,stage=?,cancel_requested=1,updated_at=? WHERE id=?",(status,status,created,run_id))
        self.runtime.record_decision(run_id,"user",status,"user kept the source scene unchanged",{});self._json({"data":self._scene_agent_payload(run_id)})
