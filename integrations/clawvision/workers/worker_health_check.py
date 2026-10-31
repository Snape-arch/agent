"""Container health command for the durable task Worker."""
from __future__ import annotations
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT/"backend"))
from worker_health import current_healthy
worker_id=os.environ.get("CLAWVISION_WORKER_ID","worker-compose")
raise SystemExit(0 if current_healthy(worker_id,int(os.environ.get("CLAWVISION_WORKER_HEALTH_MAX_AGE","45"))) else 1)
