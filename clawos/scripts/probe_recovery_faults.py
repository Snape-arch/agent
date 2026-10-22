"""Real child-process exit during partial recovery writes; disposable data only.

Fault injection exercises logical crash handling. It cannot certify physical
power-loss durability, controller caches, disk health or a real ENOSPC device.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from services.recovery_bundle import RecoveryBundle,sha,assert_workspace_complete
from services.maintenance_service import MaintenanceService
from memoryos.memory_store import MemoryStore


def bundle_for(root):
    store=MemoryStore(str(root/'live.db'))
    return RecoveryBundle(MaintenanceService(store=store,db_path=root/'live.db',base_dir=root,config={}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace');parser.add_argument('--fault',choices=['database-exit','source-exit','enospc','denied'])
    args=parser.parse_args()
    allowed=(PROJECT/'output'/'recovery-faults').resolve()
    if args.fault:
        root=Path(args.workspace).resolve()
        if root.parent!=allowed:raise ValueError('Only this probe owns the workspace')
        state=json.loads((root/'state.json').read_text())
        import services.recovery_bundle as implementation
        original=implementation.shutil.copyfile
        def interrupted(source,destination):
            database=Path(destination).name=='memoryos.db'
            if (args.fault=='source-exit' and database):return original(source,destination)
            with Path(source).open('rb') as src,Path(destination).open('wb') as dst:
                dst.write(src.read(64));dst.flush();os.fsync(dst.fileno())
            if args.fault in ('database-exit','source-exit'):os._exit(73)
            raise OSError(errno.ENOSPC if args.fault=='enospc' else errno.EACCES,'injected storage failure')
        implementation.shutil.copyfile=interrupted
        bundle_for(root).restore_isolated(state['bundle'],root/'backups'/args.fault)
        return 0
    root=allowed/uuid.uuid4().hex;root.mkdir(parents=True)
    bundle=bundle_for(root)
    bundle.ops.store.add_knowledge('Crash-recovery fixture','Committed before a simulated recovery crash.')
    from memoryos.document_ingestion import ingest_file
    source=root/'source.txt';source.write_text('Recover exactly these durable source bytes. '*8)
    ingest_file(bundle.ops.store,root/'uploads',source)
    snapshot=bundle.backup()
    before=sha(root/'live.db')
    (root/'state.json').write_text(json.dumps(dict(bundle=snapshot['path'])))
    checks={};exits={}
    for fault in ('database-exit','source-exit','enospc','denied'):
        with (root/(fault+'.log')).open('wb') as log:
            child=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--workspace',str(root),'--fault',fault],
                stdout=log,stderr=log,timeout=90)
        exits[fault]=child.returncode;target=root/'backups'/fault
        expected=73 if fault.endswith('exit') else 1
        checks[fault+'_exit']=child.returncode==expected
        checks[fault+'_no_success_report']=not (target/'recovery-report.json').exists()
        checks[fault+'_progress_survives']=(target/'RECOVERY_IN_PROGRESS.json').exists()
        try:assert_workspace_complete(target,target/'memoryos.db');blocked=False
        except ValueError:blocked=True
        checks[fault+'_live_open_refused']=blocked
    restored=bundle.restore_isolated(snapshot['path'])
    assert_workspace_complete(restored['target'],restored['database'])
    checks['fresh_retry_complete']=restored['ok'] and restored['status']=='complete'
    checks['live_database_unchanged']=before==sha(root/'live.db')
    checks['source_bundle_still_valid']=bundle.verify(snapshot['path'])[1]['schema']==bundle.SCHEMA
    result=dict(passed=all(checks.values()),checks=checks,exit_codes=exits,
        storage_failures_injected=True,actual_child_exit_verified=True,
        physical_reboot_verified=False,physical_disk_failure_verified=False,models_called=0)
    (root/'report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(passed=result['passed'],checks=checks,report=str(root/'report.json'))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
