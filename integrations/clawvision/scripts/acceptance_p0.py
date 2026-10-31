"""Run 20 complete API flows and verify that no tasks or worker processes remain."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"backend"))
import database  # noqa: E402


def call(base,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(base+path,data=data,headers={"Content-Type":"application/json"},method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request,timeout=60) as response: return json.loads(response.read())["data"]


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory); database.DB_PATH=root/"acceptance.db"; database.DATABASE_URL=f"sqlite:///{database.DB_PATH}"
        os.environ["CLAWVISION_OBJECT_DIR"]=str(root/"objects")
        import server
        from object_store import LocalObjectStore
        import text3d_service
        server.OBJECT_STORE=LocalObjectStore(); database.init_database()
        http=server.ThreadingHTTPServer(("127.0.0.1",0),server.Handler); thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        base=f"http://127.0.0.1:{http.server_port}"; jobs=[]; agents=[]
        try:
            for index in range(20):
                agents.append(call(base,"/api/studio/agent-runs",{"prompt":f"开放品类实验物体 {index}","provider":"local","qualityThreshold":85,"maxCycles":2})["id"])
                jobs.append(call(base,"/api/studio/text-to-3d",{"prompt":f"非模板语义生物 {index}","provider":"local-implicit","resolution":24})["id"])
            deadline=time.time()+180
            while time.time()<deadline:
                agent_states=[call(base,f"/api/studio/agent-runs/{item}")["status"] for item in agents]
                job_states=[call(base,f"/api/studio/text-to-3d/{item}")["status"] for item in jobs]
                if all(state in {"completed","failed","cancelled"} for state in agent_states+job_states): break
                time.sleep(.25)
            assert all(state=="completed" for state in agent_states),agent_states
            assert all(state=="completed" for state in job_states),job_states
            for job_id in jobs:
                job=call(base,f"/api/studio/text-to-3d/{job_id}"); asset=call(base,f"/api/model-assets/{job['assetId']}")
                assert asset["format"]=="glb" and asset["content"]["base64"].startswith("Z2xURg")
            with database.connect() as db:
                pending_agents=db.execute("SELECT COUNT(*) AS count FROM agent_runs WHERE status NOT IN ('completed','failed','cancelled')").fetchone()["count"]
                pending_jobs=db.execute("SELECT COUNT(*) AS count FROM text3d_jobs WHERE status NOT IN ('completed','failed','cancelled')").fetchone()["count"]
            assert pending_agents==pending_jobs==0 and not text3d_service.ACTIVE
            print(json.dumps({"ok":True,"flows":20,"agents":agent_states.count("completed"),"text3d":job_states.count("completed"),"activeWorkers":len(text3d_service.ACTIVE)}))
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=5); server.EXECUTOR.shutdown(wait=True,cancel_futures=True)


if __name__=="__main__": main()
