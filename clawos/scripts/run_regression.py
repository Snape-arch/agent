"""Run the full suite with tool subprocess DB/output isolated from user data."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
import argparse


def main():
    project=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--pattern',default='test*.py',help='unittest discovery filename pattern')
    parser.add_argument('--verbose',action='store_true',help='log each test for long-run progress inspection')
    args=parser.parse_args()
    root=project/'output'/'regression'/uuid.uuid4().hex
    root.mkdir(parents=True)
    env=dict(os.environ,CLAWOS_MEMORY_DB=str(root/'memoryos.db'),CLAWOS_OUTPUT_DIR=str(root/'artifacts'),PYTHONPATH=str(project)+os.pathsep+os.environ.get('PYTHONPATH',''))
    print('Isolated regression workspace: '+str(root),flush=True)
    command=[sys.executable,'-m','unittest','discover','-s',str(project/'tests'),'-p',args.pattern]
    if args.verbose:command.append('-v')
    result=subprocess.run(command,
        cwd=project.parent,env=env)
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
