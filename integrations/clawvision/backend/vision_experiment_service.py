"""Lease-fenced real image fitting, checkpoint recovery and held-out comparison."""
import hashlib
import json
import math
import os
import threading
import time
import uuid
from contextlib import nullcontext

from api_contract import page_meta
from errors import ConflictError, NotFoundError, ValidationError
from evaluation_service import EvaluationService, canonical, digest, text
from run_service import RunService
from scenario_service import integer
from security import reserve_storage
from synthesis_service import SynthesisService, LeaseLost, now
from vision_dataset_service import VisionDatasetService
import vision_model as model

def config(value):
    if not isinstance(value,dict) or set(value)-{"seed","epochs","learningRate","regularization"}: raise ValidationError("invalid CPU training config")
    result = {"seed":integer(value.get("seed",42),"seed",0,2**32-1), "epochs":integer(value.get("epochs",50),"epochs",1,200)}
    for field, default, low, high in (("learningRate",.1,.0001,1),("regularization",.001,0,1)):
        v = value.get(field,default)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low<=v<=high: raise ValidationError(f"invalid {field}")
        result[field] = v
    return {**result,"environment":model.environment()}

class VisionExperimentService:
    def __init__(self, connect, store, lock):
        self.connect, self.store, self.lock = connect, store, lock
        self.datasets = VisionDatasetService(connect,store,lock)

    @staticmethod
    def _row(db, tenant, experiment_id):
        row = db.execute("SELECT e.*,t.status AS task_status,t.error AS task_error,t.attempts FROM vision_experiments e JOIN durable_tasks t ON t.id=e.task_id WHERE e.id=? AND e.tenant_id=?",(experiment_id,tenant)).fetchone()
        if not row: raise NotFoundError("vision experiment not found")
        return row

    @staticmethod
    def _json(row):
        status = row["status"]
        if status!="completed":
            status = {"queued":"queued","leased":"running","cancelled":"cancelled","dead-letter":"failed"}.get(row["task_status"],status)
        state, cfg = json.loads(row["state_json"]),json.loads(row["config_json"])
        return {"id":row["id"],"taskId":row["task_id"],"status":status,"attempts":row["attempts"],
                "realTrainVersionId":row["real_train_version_id"],"syntheticVersionId":row["synthetic_version_id"],"testVersionId":row["test_version_id"],
                "baselineRunId":row["baseline_run_id"],"candidateRunId":row["candidate_run_id"],"testSetId":row["test_set_id"],
                "config":cfg,"epochsCompleted":sum(s.get("checkpoint",{}).get("epoch",0) for s in state.values()),"totalEpochs":cfg["epochs"]*2,
                "result":json.loads(row["result_json"]) if row["result_json"] else None,
                "error":None if status=="completed" else row["error"] or row["task_error"],"createdAt":row["created_at"],"updatedAt":row["updated_at"]}

    def get(self, tenant, experiment_id):
        with self.connect() as db: return self._json(self._row(db,tenant,experiment_id))

    def list(self, tenant, pagination):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM vision_experiments WHERE tenant_id=?",(tenant,)).fetchone()["n"]
            rows = db.execute("SELECT e.*,t.status AS task_status,t.error AS task_error,t.attempts FROM vision_experiments e JOIN durable_tasks t ON t.id=e.task_id WHERE e.tenant_id=? ORDER BY e.created_at DESC,e.id DESC LIMIT ? OFFSET ?",(tenant,pagination.page_size,pagination.offset)).fetchall()
        return {"data":[self._json(r) for r in rows],"pagination":page_meta(pagination,total)}

    def inputs(self, tenant, real_id, synthetic_id, test_id):
        versions = [self.datasets.get(tenant,v) for v in (real_id,synthetic_id,test_id)]
        if [(v["origin"],v["purpose"]) for v in versions] != [("real","train"),("synthetic","train"),("real","test")]:
            raise ValidationError("select real training, synthetic training and independent real test versions")
        train, synth, test = [v["manifest"] for v in versions]
        classes = train["classes"]
        if not 2 <= len(classes) <= 100: raise ValidationError("real training data must cover 2 to 100 classes")
        if not set(synth["classes"]+test["classes"]) <= set(classes): raise ValidationError("synthetic and test labels must be covered by real training classes")
        def hashes(samples):
            return {h for s in samples for h in (s["pixelHash"],s["image"]["sha256"],s["originalSha256"])}
        test_hashes = hashes(test["samples"])
        if hashes(train["samples"]+synth["samples"]) & test_hashes: raise ValidationError("training and held-out test images overlap")
        source = synth["lineage"]["source"]
        with self.connect() as db:
            source_set = db.execute("SELECT dataset_version_id FROM evaluation_test_sets WHERE id=? AND tenant_id=?",(source["testSetId"],tenant)).fetchone()
            if source_set and source_set["dataset_version_id"] == test_id: raise ValidationError("test version already participated in synthetic scene design")
            known = db.execute("SELECT content_hash FROM evaluation_samples WHERE test_set_id=? AND content_hash IS NOT NULL",(source["testSetId"],)).fetchall()
        if any(r["content_hash"] in test_hashes for r in known): raise ValidationError("held-out images were used for synthetic scene design")
        return versions

    def create(self, tenant, body):
        if not isinstance(body,dict) or set(body)-{"realTrainVersionId","syntheticVersionId","testVersionId","config"}: raise ValidationError("invalid experiment fields")
        ids = [text(body.get(k),k) for k in ("realTrainVersionId","syntheticVersionId","testVersionId")]
        versions, cfg = self.inputs(tenant,*ids),config(body.get("config",{}))
        cfg["datasetDigests"] = [v["digest"] for v in versions]
        signature = digest({"ids":ids,"config":cfg})
        experiment_id, task_id = "vexp_"+uuid.uuid4().hex,"task_"+uuid.uuid4().hex
        baseline, candidate = "run_"+uuid.uuid4().hex[:16],"run_"+uuid.uuid4().hex[:16]
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT id FROM vision_experiments WHERE tenant_id=? AND request_digest=?",(tenant,signature)).fetchone()
            if existing: return self._json(self._row(db,tenant,existing["id"]))
            SynthesisService._quota(db,tenant)
            quota = db.execute("SELECT max_runs FROM tenant_quotas WHERE tenant_id=?",(tenant,)).fetchone()
            count = db.execute("SELECT COUNT(*) AS n FROM runs WHERE tenant_id=?",(tenant,)).fetchone()["n"]
            if quota and count+2 > quota["max_runs"]: raise PermissionError("tenant run quota exceeded")
            evaluation = EvaluationService(lambda: nullcontext(db))
            samples = versions[2]["manifest"]["samples"]
            test_set = evaluation.create_test_set(tenant,{"name":versions[2]["name"]+" · frozen CPU test","classes":versions[0]["classes"],"datasetVersionId":ids[2],
                "samples":[{"id":s["id"],"label":s["label"],"conditions":s["conditions"],"contentHash":s["image"]["sha256"],
                            "imageUri":f"/api/evaluation/image-versions/{ids[2]}/images/{i}"} for i,s in enumerate(samples)]})
            timestamp = now()
            for run_id, arm in ((baseline,"baseline"),(candidate,"candidate")):
                params = {**cfg,"experimentId":experiment_id,"arm":arm,"datasetVersionIds":[ids[0]]+([ids[1]] if arm=="candidate" else []),"testVersionId":ids[2]}
                db.execute("INSERT INTO runs(id,tenant_id,name,status,source,params,created_at,updated_at) VALUES(?,?,?,'queued',?,?,?,?)",
                           (run_id,tenant,"仅真实数据" if arm=="baseline" else "真实＋合成数据",model.PROVIDER,canonical(params),timestamp,timestamp))
            db.execute("INSERT INTO durable_tasks(id,tenant_id,kind,resource_id,payload,status,priority,attempts,max_attempts,idempotency_key,created_at,updated_at) VALUES(?,?,'vision-experiment',?,'{}','queued',40,0,3,?,?,?)",
                       (task_id,tenant,experiment_id,"vision:"+signature,timestamp,timestamp))
            db.execute("INSERT INTO vision_experiments(id,tenant_id,task_id,real_train_version_id,synthetic_version_id,test_version_id,test_set_id,baseline_run_id,candidate_run_id,config_json,request_digest,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)",
                       (experiment_id,tenant,task_id,*ids,test_set["id"],baseline,candidate,canonical(cfg),signature,timestamp,timestamp))
            return self._json(self._row(db,tenant,experiment_id))

    def action(self, tenant, experiment_id, action):
        with self.lock,self.connect() as db:
            row = self._row(db,tenant,experiment_id)
            if row["status"]=="completed": raise ConflictError("completed experiments are immutable")
            if action=="cancel": status = "cancelled"
            elif action=="retry":
                if row["task_status"] not in {"cancelled","dead-letter","failed"}: raise ConflictError("retry requires a terminal failed or cancelled task")
                SynthesisService._quota(db,tenant); status = "queued"
            else: raise ValidationError("invalid experiment action")
            db.execute("UPDATE durable_tasks SET status=?,attempts=0,lease_owner=NULL,lease_expires_at=NULL,error=NULL,updated_at=? WHERE id=?",(status,now(),row["task_id"]))
            db.execute("UPDATE vision_experiments SET status=?,error=NULL,updated_at=? WHERE id=?",(status,now(),experiment_id))
            db.execute("UPDATE runs SET status=?,updated_at=? WHERE id IN (?,?) AND status!='completed'",("stopped" if status=="cancelled" else "queued",now(),row["baseline_run_id"],row["candidate_run_id"]))
            return self._json(self._row(db,tenant,experiment_id))

    def execute(self, tenant, experiment_id, owner):
        with self.connect() as db:
            row = self._row(db,tenant,experiment_id)
            if row["status"]=="completed": return {"experimentId":experiment_id}
            SynthesisService._fence(db,row["task_id"],owner)
            db.execute("UPDATE vision_experiments SET status='running',error=NULL,updated_at=? WHERE id=?",(now(),experiment_id))
        cfg, state, deadline = json.loads(row["config_json"]),json.loads(row["state_json"]),time.monotonic()+180
        def check(db):
            if time.monotonic()>deadline: raise ValidationError("CPU experiment exceeded 180 seconds")
            SynthesisService._fence(db,row["task_id"],owner)
        try:
            if model.environment()!=cfg["environment"]: raise ConflictError("CPU model environment changed; create a new experiment")
            versions = self.inputs(tenant,row["real_train_version_id"],row["synthetic_version_id"],row["test_version_id"])
            if [v["digest"] for v in versions]!=cfg["datasetDigests"]: raise ConflictError("training version digest changed")
            np = model.numpy()
            arrays = []
            for version in versions:
                x, labels = [], []
                for sample in version["manifest"]["samples"]:
                    with self.connect() as db: check(db)
                    x.append(model.features(self.datasets._verified(sample["image"])))
                    labels.append(sample["label"])
                arrays.append((np.stack(x),labels))
            classes = versions[0]["classes"]
            for arm, run_id in (("baseline",row["baseline_run_id"]),("candidate",row["candidate_run_id"])):
                saved = state.get(arm,{})
                if saved.get("reportId"):
                    if hashlib.sha256(self.store.get_bytes(saved["modelKey"])).hexdigest()!=saved["modelSha256"]: raise ConflictError("saved model hash changed")
                    continue
                x, labels = arrays[0]
                if arm=="candidate": x, labels = np.concatenate((x,arrays[1][0])),labels+arrays[1][1]
                y = np.array([classes.index(label) for label in labels])
                checkpoint = saved.get("checkpoint") or model.initial(x,classes,cfg["seed"])
                if saved.get("checkpoint") and digest(checkpoint)!=saved.get("checkpointDigest"): raise ConflictError("CPU checkpoint hash changed")
                with self.connect() as db:
                    check(db); db.execute("UPDATE runs SET status='running',error_message=NULL,updated_at=? WHERE id=?",(now(),run_id))
                while checkpoint["epoch"]<cfg["epochs"]:
                    checkpoint, loss = model.step(x,y,checkpoint,cfg["learningRate"],cfg["regularization"])
                    state[arm] = {"checkpoint":checkpoint,"checkpointDigest":digest(checkpoint)}
                    with self.connect() as db:
                        check(db)
                        RunService.insert_metric(db,run_id,{"step":checkpoint["epoch"],"trainLoss":loss,"learningRate":cfg["learningRate"]})
                        db.execute("UPDATE vision_experiments SET state_json=?,updated_at=? WHERE id=?",(canonical(state),now(),experiment_id))
                predicted = model.probabilities(arrays[2][0],checkpoint)
                predictions = [{"sampleId":s["id"],"label":classes[int(p.argmax())],"confidence":float(p.max())} for s,p in zip(versions[2]["manifest"]["samples"],predicted)]
                content = canonical({**checkpoint,"config":cfg,"trainingSamples":len(labels),"trainingVersionIds":[versions[0]["id"]]+([versions[1]["id"]] if arm=="candidate" else [])}).encode()
                key = f"tenants/{tenant}/vision/models/{experiment_id}/{uuid.uuid4().hex}.json"
                reserve_storage(tenant,len(content)); self.store.put_bytes(key,content,"application/json")
                artifact_id = "art_"+uuid.uuid4().hex
                with self.connect() as db:
                    check(db)
                    db.execute("INSERT INTO artifacts(id,run_id,name,type,mime_type,step,object_key,created_at) VALUES(?,?,?,'model','application/json',?,?,?)",(artifact_id,run_id,model.PROVIDER,cfg["epochs"],key,now()))
                    db.execute("UPDATE runs SET status='completed',updated_at=? WHERE id=?",(now(),run_id))
                    evaluation = EvaluationService(lambda: nullcontext(db),model.PROVIDER).create_evaluation(tenant,{"testSetId":row["test_set_id"],"runId":run_id,"predictions":predictions,"modelArtifactId":artifact_id})
                    state[arm].update({"reportId":evaluation["id"],"modelKey":key,"modelSha256":hashlib.sha256(content).hexdigest(),"modelArtifactId":artifact_id,"trainingSamples":len(labels)})
                    db.execute("UPDATE vision_experiments SET state_json=?,updated_at=? WHERE id=?",(canonical(state),now(),experiment_id))
            result = EvaluationService(self.connect).compare(tenant,state["baseline"]["reportId"],state["candidate"]["reportId"])
            result.update({"provider":model.PROVIDER,"datasetDigests":cfg["datasetDigests"],"trainingSamples":{k:s["trainingSamples"] for k,s in state.items()},
                           "modelSha256":{k:s["modelSha256"] for k,s in state.items()},"leakageChecks":"known design versions and exact byte/pixel hashes; near-duplicates and unknown provenance require review"})
            with self.connect() as db:
                check(db); db.execute("UPDATE vision_experiments SET status='completed',result_json=?,error=NULL,updated_at=? WHERE id=?",(canonical(result),now(),experiment_id))
            return {"experimentId":experiment_id}
        except Exception as error:
            try:
                with self.connect() as db:
                    SynthesisService._fence(db,row["task_id"],owner)
                    db.execute("UPDATE vision_experiments SET status='failed',error=?,updated_at=? WHERE id=?",(str(error)[:2000],now(),experiment_id))
                    db.execute("UPDATE runs SET status='failed',error_message=?,updated_at=? WHERE id IN (?,?) AND status!='completed'",(str(error)[:2000],now(),row["baseline_run_id"],row["candidate_run_id"]))
            except LeaseLost: pass
            raise

def execute_vision_experiment(experiment_id, tenant, owner=None):
    from database import connect
    from server import DB_LOCK, OBJECT_STORE
    return VisionExperimentService(connect,OBJECT_STORE,DB_LOCK).execute(tenant,experiment_id,owner or f"worker-{os.getpid()}-{threading.get_ident()}")
