"""Run the full suite with tool subprocess DB/output isolated from user data."""
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    project=Path(__file__).resolve().parents[1]
    root=project/'output'/'regression'/uuid.uuid4().hex
    root.mkdir(parents=True)
    env=dict(os.environ,CLAWOS_MEMORY_DB=str(root/'memoryos.db'),CLAWOS_OUTPUT_DIR=str(root/'artifacts'))
    print('Isolated regression workspace: '+str(root),flush=True)
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(project/'tests')],
        cwd=project.parent,env=env)
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
