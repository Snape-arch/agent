"""Read-only live snapshot + isolated full-source/vector recovery. Never switches live DB."""
import argparse
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.maintenance_service import MaintenanceService
from services.recovery_bundle import RecoveryBundle,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-db',required=True);p.add_argument('--base-dir',required=True)
    p.add_argument('--material-root');p.add_argument('--vector-config',help='Optional local config: reuse external weights, create a new isolated vector directory')
    args=p.parse_args();base=Path(args.base_dir).resolve();db=Path(args.source_db).resolve()
    if base not in db.parents:p.error('Source DB must belong to the explicitly named project directory')
    if args.vector_config:
        from services.config_environment import resolve_environment
        config=resolve_environment(json.loads(Path(args.vector_config).read_text(encoding='utf-8-sig')))
    else:config={}
    guard=SimpleNamespace(_lock=threading.RLock())
    ops=MaintenanceService(store=guard,db_path=db,base_dir=base,config={})
    import os
    material_root=args.material_root or str(Path(os.environ.get('CLAWOS_OUTPUT_DIR',str(base.parent/'output')))/'academy-materials')
    bundle=RecoveryBundle(ops,material_root)
    before=sha(db);health=ops.database_health()
    if not health['ok']:raise RuntimeError('Live read-only health failed; no recovery drill started')
    backup=bundle.backup('read-only-drill')
    factory=None
    if args.vector_config:
        from memoryos.services.vector_store import MemoryVectorStore
        cfg=config.get('vector_store') or {}
        model=cfg.get('embedding_model_path') or ''
        if model and not Path(model).is_absolute():model=str((base/model).resolve())
        def factory(path,persist):
            v=MemoryVectorStore(path,provider=cfg.get('provider') or 'lightweight',persist_dir=str(persist),
                embedding_provider=cfg.get('embedding_provider') or 'hash',embedding_model_path=model,
                embedding_dim=cfg.get('embedding_dim') or 0)
            if v.fallback_reason:
                v.close();raise RuntimeError('Configured vector backend fell back; real backend recovery is not proven')
            return v
    result=bundle.restore_isolated(backup['path'],vector_factory=factory)
    report=dict(backup=backup,recovery=result,live_db_hash_unchanged=before==sha(db),source_health=health,
        configured_backend=bool(args.vector_config),model_weights_copied=False)
    target=Path(result['target'])/'drill-report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(ok=result['ok'],files=result['source_files'],vector=result['vector'],live_db_hash_unchanged=report['live_db_hash_unchanged'],report=str(target)),ensure_ascii=False))
if __name__=='__main__':main()
