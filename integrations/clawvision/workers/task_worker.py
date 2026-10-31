"""Standalone durable worker for all ClawVision background task kinds."""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT/"backend"))

from database import connect, init_database  # noqa: E402
from durable_queue import claim, fail, finish, heartbeat, queue_metrics, reap_expired  # noqa: E402
from security import Principal  # noqa: E402
from server import (Handler, OBJECT_STORE, execute_agent_pipeline, execute_queued_run,
                    execute_real_training, execute_text3d_job, json_value)  # noqa: E402
from observability import gauge, inc, render_prometheus, span  # noqa: E402
from worker_health import remove as remove_health, write as write_health
from synthesis_service import execute_synthesis_job  # noqa: E402
from vision_experiment_service import execute_vision_experiment  # noqa: E402

STOP=threading.Event()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            payload=b"ok\n";status=200
        elif self.path == "/metrics":
            queue_metrics();payload=render_prometheus().encode();status=200
        else:
            payload=b"not found\n";status=404
        self.send_response(status);self.send_header("Content-Type","text/plain; version=0.0.4");self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)

    def log_message(self,*_): pass


def _handler(tenant_id: str):
    item=object.__new__(Handler);item.principal=Principal("worker",tenant_id,"owner",("*",));return item


def execute(task: dict) -> dict:
    kind=task["kind"];resource=task["resourceId"];payload=task["payload"]
    if kind=="synthesis": return execute_synthesis_job(resource, task["tenantId"], task["leaseOwner"])
    if kind=="vision-experiment": return execute_vision_experiment(resource, task["tenantId"], task["leaseOwner"])
    if kind=="agent-pipeline": execute_agent_pipeline(resource,payload,OBJECT_STORE)
    elif kind=="text-to-3d":
        with connect() as db: row=db.execute("SELECT * FROM text3d_jobs WHERE id=?",(resource,)).fetchone()
        if not row: raise RuntimeError("text-to-3d job not found")
        image=None
        if row["input_image_key"]:
            image=OBJECT_STORE.get_json(row["input_image_key"]).get("base64")
        execute_text3d_job(resource,row["prompt"],38,OBJECT_STORE,row["provider"],image,row["timeout_seconds"],row["memory_budget_mb"])
    elif kind=="training":
        run_id=str(payload["runId"]);provider=str(payload.get("provider") or "simulator")
        with connect() as db:
            run=db.execute("SELECT params FROM runs WHERE id=? AND tenant_id=?",(run_id,task["tenantId"])).fetchone()
            if not run: raise RuntimeError("training run not found")
            params=json_value(run["params"],{});job_id=str(params.get("_jobId") or "")
            if provider!="simulator":
                row=db.execute("SELECT * FROM training_jobs WHERE id=? AND run_id=? AND tenant_id=?",(resource,run_id,task["tenantId"])).fetchone()
                if not row: raise RuntimeError("training job not found")
        if provider=="simulator": execute_queued_run(run_id,params,job_id,threading.Semaphore(1))
        else: execute_real_training(resource,run_id,params,job_id,provider,threading.Semaphore(1),row["timeout_seconds"])
    elif kind=="scene-agent": _handler(task["tenantId"])._execute_scene_agent(resource,False)
    elif kind=="geometry": _handler(task["tenantId"])._execute_geometry_job(resource)
    elif kind=="model-operation": _handler(task["tenantId"])._execute_model_operation(resource)
    else: raise RuntimeError(f"unsupported task kind: {kind}")
    table={"agent-pipeline":"agent_runs","text-to-3d":"text3d_jobs",
           "scene-agent":"scene_agent_runs","geometry":"geometry_jobs",
           "model-operation":"model_operation_jobs"}.get(kind)
    if kind=="training":table="runs" if payload.get("provider")=="simulator" else "training_jobs"
    with connect() as db:
        row=db.execute(f"SELECT status FROM {table} WHERE id=?",(resource,)).fetchone() if table else None
    status=row["status"] if row else "missing"
    if status in {"failed","dead-letter","missing"}:
        raise RuntimeError(f"resource finished as {status}")
    return {"resourceId":resource,"kind":kind,"resourceStatus":status}


def main() -> None:
    init_database();worker_id=os.environ.get("CLAWVISION_WORKER_ID",f"worker-{uuid.uuid4().hex[:8]}")
    lease_seconds=max(5,int(os.environ.get("CLAWVISION_WORKER_LEASE_SECONDS","30")))
    metrics=ThreadingHTTPServer(("0.0.0.0",int(os.environ.get("CLAWVISION_WORKER_METRICS_PORT","9091"))),MetricsHandler)
    threading.Thread(target=metrics.serve_forever,daemon=True).start()
    completed=0;failed=0;write_health(worker_id,state="idle",completed=completed,failed=failed)
    for event in (signal.SIGINT,signal.SIGTERM): signal.signal(event,lambda *_:STOP.set())
    while not STOP.is_set():
        reap_expired();task=claim(worker_id,lease_seconds=lease_seconds)
        if not task: gauge("clawvision_worker_busy",0,worker=worker_id);write_health(worker_id,state="idle",completed=completed,failed=failed);STOP.wait(.5);continue
        gauge("clawvision_worker_busy",1,worker=worker_id)
        write_health(worker_id,state="busy",task_id=task["id"],kind=task["kind"],completed=completed,failed=failed)
        renewing=threading.Event()
        def renew():
            while not renewing.wait(min(10,lease_seconds/3)):
                heartbeat(task["id"],worker_id,lease_seconds)
                write_health(worker_id,state="busy",task_id=task["id"],kind=task["kind"],completed=completed,failed=failed)
        thread=threading.Thread(target=renew,daemon=True);thread.start()
        try:
            with span("worker.task",traceparent=task["payload"].get("_traceparent"),worker=worker_id,kind=task["kind"],taskId=task["id"]):
                finish(task["id"],worker_id,execute(task));completed+=1;inc("clawvision_worker_tasks_total",worker=worker_id,kind=task["kind"],status="completed")
        except Exception as error:
            fail(task["id"],worker_id,str(error),retry=True);failed+=1;inc("clawvision_worker_tasks_total",worker=worker_id,kind=task["kind"],status="failed")
        finally: renewing.set();thread.join(timeout=.2);gauge("clawvision_worker_busy",0,worker=worker_id);write_health(worker_id,state="idle",completed=completed,failed=failed)
    remove_health(worker_id);metrics.shutdown();metrics.server_close()


if __name__=="__main__": main()
