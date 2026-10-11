"""Prepare/inspect the default private runtime without environment setup."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.sandbox_runtime import SandboxRuntime, sandbox_storage


def inspect_quarantine():
    rows=[]
    for path in (sandbox_storage()/'commands').glob('*/request.json'):
        receipt=path.with_name('result.json')
        workspace=None
        try:
            request=json.loads(path.read_text(encoding='utf-8'))
            workspace=request['workspace']
            if not isinstance(workspace,str): raise ValueError('invalid workspace')
            data=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
            bound=data.get('request_digest')==hashlib.sha256(path.read_bytes()).hexdigest()
            if data.get('cleanup_verified') is True and bound: continue
            error=data.get('error') or ('request digest mismatch' if data.get('cleanup_verified') else 'cleanup not verified')
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            error='invalid supervisor journal: '+type(exc).__name__
        rows.append(dict(receipt=str(receipt),workspace=workspace,state='unresolved',error=error))
    setup_state=SandboxRuntime().root/'setup-state.json'
    try:
        setup=json.loads(setup_state.read_text(encoding='utf-8')) if setup_state.exists() else None
        if setup is not None and not isinstance(setup,dict): raise ValueError('invalid setup state')
    except (OSError,ValueError) as exc:
        setup=dict(phase='unknown',cleanup_verified=False,error=type(exc).__name__)
    setup_pending=setup is not None and not (setup.get('phase')=='complete' or setup.get('cleanup_verified') is True)
    return dict(unresolved=rows,setup_state=setup,setup_pending=setup_pending,
                automatic_release=False,production_sandbox_ready=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['setup','status','quarantine'])
    parser.add_argument('--confirmed',action='store_true',help='authorize owned runtime/profile creation')
    args=parser.parse_args()
    if args.operation=='setup': result=SandboxRuntime().prepare(confirmed=args.confirmed)
    elif args.operation=='status': result=SandboxRuntime().status()
    else: result=inspect_quarantine()
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('error') or result.get('unresolved') or result.get('setup_pending') else 0


if __name__=='__main__':raise SystemExit(main())
