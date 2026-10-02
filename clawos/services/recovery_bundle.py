"""Portable source bundle and isolated recovery drill; model weights stay external."""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def inside(root,value):
    root=Path(root).resolve();path=(root/value).resolve()
    if root not in path.parents:raise ValueError('备份文件路径越界')
    return path


def rebind_json_paths(connection,mapping):
    """Rebind exact JSON path values; leave prose and archived source bytes intact."""
    def replace(value):
        if isinstance(value,str):return mapping.get(value,value)
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    quote=lambda s:'"'+s.replace('"','""')+'"'
    changed=0
    tables=connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for name,sql in tables:
        if 'WITHOUT ROWID' in (sql or '').upper():continue
        table=quote(name)
        columns=[r[1] for r in connection.execute('PRAGMA table_info('+table+')') if r[2].upper()=='TEXT']
        for name in columns:
            column=quote(name)
            for rowid,text in connection.execute(f'SELECT rowid,{column} FROM {table} WHERE json_valid({column})').fetchall():
                old=json.loads(text);new=replace(old)
                if new!=old:
                    connection.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?',(json.dumps(new,ensure_ascii=False),rowid));changed+=1
    return changed


class RecoveryBundle:
    SCHEMA='clawos.recovery-bundle.v1'
    EXCLUDED={'.gguf','.safetensors','.onnx','.pt','.pth','.ckpt','.traineddata'}

    def __init__(self,maintenance,material_root=None):
        self.ops=maintenance
        self.material_root=Path(material_root or maintenance.base_dir/'output'/'academy-materials').resolve()

    def _sources(self,db):
        refs=[]
        with closing(sqlite3.connect(db)) as c:
            c.row_factory=sqlite3.Row
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'documents' in tables:
                for r in c.execute("SELECT id,file_path FROM documents WHERE file_path<>''"):
                    refs.append(dict(kind='document',id=r['id'],path=r['file_path']))
            if 'academy_materials' in tables:
                for r in c.execute('SELECT id,filename,digest FROM academy_materials'):
                    refs.append(dict(kind='material',id=r['id'],path=str(inside(self.material_root,Path(r['id'])/r['filename'])),expected_sha=r['digest']))
            if 'run_artifacts' in tables:
                for r in c.execute("SELECT id,uri FROM run_artifacts WHERE uri<>''"):
                    if '://' not in r['uri'] and Path(r['uri']).is_absolute():
                        refs.append(dict(kind='artifact',id=r['id'],path=r['uri']))
        return refs

    def backup(self,label='complete'):
        target=self.ops.base_dir/'backups'/('bundle-'+uuid.uuid4().hex)
        target.mkdir(parents=True)
        try:
            # The shared store lock provides a single committed DB cut for in-process writes.
            with self.ops.store._lock:
                snapshot=self.ops.backup_database(str(target),label)
                db=Path(snapshot['path']);refs=self._sources(db)
                entries=[];copied={};missing_artifacts=[]
                for ref in refs:
                    source=Path(ref['path']).resolve()
                    if any(p.lower()=='tools' for p in source.parts) or source.suffix.lower() in self.EXCLUDED:
                        raise ValueError('资料引用指向模型权重或 tools；完整资料备份拒绝包含该路径')
                    if not source.is_file():
                        if ref['kind']=='artifact':
                            missing_artifacts.append(dict(**ref,reason='registered_file_missing'));continue
                        raise ValueError('资料原文件缺失，完整备份未成立：'+str(source))
                    before=sha(source)
                    if ref.get('expected_sha') and ref['expected_sha']!=before:raise ValueError('学习材料原文件与数据库摘要不一致')
                    relative=copied.get(str(source))
                    if not relative:
                        relative='files/'+uuid.uuid4().hex+source.suffix.lower()
                        dest=inside(target,relative);dest.parent.mkdir(exist_ok=True);shutil.copyfile(source,dest)
                        if sha(dest)!=before or sha(source)!=before:raise ValueError('资料备份期间发生变化，请在写入结束后重试')
                        copied[str(source)]=relative
                    entries.append(dict(**ref,bundle_path=relative,sha256=before,bytes=source.stat().st_size))
                manifest=dict(schema=self.SCHEMA,created_at=self.ops._now(),database=dict(path=db.name,sha256=sha(db)),files=entries,
                    material_root=str(self.material_root),vector_recovery='rebuild_from_canonical_sqlite',
                    weights_included=False,missing_artifacts=missing_artifacts,
                    scope='SQLite, all referenced document/material originals and existing registered local run artifacts; missing historical artifacts explicitly inventoried. Vectors rebuilt from canonical records. Unregistered files and model weights excluded.')
                (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            return dict(ok=True,status='degraded' if missing_artifacts else 'complete',path=str(target),source_files=len(entries),unique_files=len(copied),
                missing_artifacts=len(missing_artifacts),complete_original_sources=True,scope=manifest['scope'],weights_included=False)
        except Exception:
            # Keep failed snapshots for diagnosis, never advertise them as complete.
            (target/'INCOMPLETE.txt').write_text('Backup failed; do not restore this directory.',encoding='utf-8')
            raise

    def verify(self,bundle):
        folder=Path(bundle).resolve()
        if (folder/'INCOMPLETE.txt').exists():raise ValueError('备份未完成')
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('schema')!=self.SCHEMA or manifest.get('weights_included') is not False:raise ValueError('不支持的恢复包')
        db=inside(folder,manifest['database']['path'])
        if sha(db)!=manifest['database']['sha256']:raise ValueError('数据库备份摘要不一致')
        self.ops._assert_sqlite_ok(db)
        refs=self._sources(db)
        expected={(r['kind'],str(r['id'])) for r in refs}
        actual={(r['kind'],str(r['id'])) for r in manifest['files']}
        missing=manifest.get('missing_artifacts',[])
        if any(r.get('kind')!='artifact' for r in missing):raise ValueError('原始资料不能作为缺失产物略过')
        missing_ids={(r['kind'],str(r['id'])) for r in missing}
        if expected!=actual|missing_ids or actual&missing_ids or len(actual)!=len(manifest['files']) or len(missing_ids)!=len(missing):raise ValueError('恢复包资料清单不完整或重复')
        for ref in manifest['files']:
            source=inside(folder,ref['bundle_path'])
            if sha(source)!=ref['sha256'] or source.stat().st_size!=ref['bytes']:raise ValueError('资料备份摘要不一致')
        return folder,manifest

    def restore_isolated(self,bundle,target_dir='',vector_factory=None):
        """Restore into a NEW sibling workspace; never replace the running user's DB."""
        folder,manifest=self.verify(bundle)
        root=Path(target_dir).resolve() if target_dir else self.ops.base_dir/'backups'/('recovery-'+uuid.uuid4().hex)
        allowed=(self.ops.base_dir/'backups').resolve()
        if allowed not in root.parents:raise ValueError('隔离恢复目录必须位于本项目 backups 内')
        if root.exists():raise ValueError('恢复目录必须是新目录，不能覆盖已有资料')
        root.mkdir(parents=True)
        db=root/'memoryos.db';shutil.copyfile(inside(folder,manifest['database']['path']),db)
        mapping={};restored_materials=root/'output'/'academy-materials'
        try:
            for ref in manifest['files']:
                if ref['kind']=='material':
                    original=Path(ref['path'])
                    destination=inside(restored_materials,Path(str(ref['id']))/original.name)
                else:destination=inside(root,'sources/'+ref['bundle_path'].split('/')[-1])
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(inside(folder,ref['bundle_path']),destination)
                if sha(destination)!=ref['sha256']:raise ValueError('恢复后的资料摘要不一致')
                mapping[ref['path']]=str(destination)
            with closing(sqlite3.connect(db)) as c:
                names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for ref in manifest['files']:
                    if ref['kind']=='document':c.execute('UPDATE documents SET file_path=? WHERE id=?',(mapping[ref['path']],ref['id']))
                    elif ref['kind']=='artifact':c.execute('UPDATE run_artifacts SET uri=? WHERE id=?',(mapping[ref['path']],ref['id']))
                rebound=rebind_json_paths(c,mapping)
                # A restored SQL snapshot must not claim an external index is already current.
                if 'knowledge_vector_index_state_v2' in names:c.execute('DELETE FROM knowledge_vector_index_state_v2')
                if 'knowledge_vector_outbox_v2' in names:c.execute("UPDATE knowledge_vector_outbox_v2 SET processed_at='',error=''")
                c.commit()
            from memoryos.memory_store import MemoryStore
            from services.maintenance_service import MaintenanceService
            from memoryos.services.vector_store import MemoryVectorStore
            store=MemoryStore(str(db));ops=MaintenanceService(store=store,db_path=db,base_dir=root,config={})
            ops.apply_migrations()
            vector=vector_factory(str(db),root/'vectors') if vector_factory else MemoryVectorStore(str(db),provider='lightweight',embedding_provider='hash')
            try:
                stats=vector.rebuild()
                if not stats.get('consistent'):raise ValueError('向量重建未达到记录与 outbox 一致')
                rows=[vector._store.get(row['id']) for row in vector._store.list_all()]
                # Exact payload projection survives independently of backend binary formats.
                portable=root/'vectors'/'projection.json';portable.parent.mkdir(exist_ok=True)
                portable.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                health=ops.database_health()
                if not health['ok']:raise ValueError('隔离恢复后的数据库或原文件检查失败')
                result=dict(ok=True,status='degraded' if manifest.get('missing_artifacts') else 'complete',missing_artifacts=len(manifest.get('missing_artifacts',[])),
                    target=str(root),database=str(db),material_root=str(restored_materials),source_files=len(manifest['files']),rebound_json_fields=rebound,health=health,
                    vector=dict(provider=stats['provider'],embedding_provider=stats['embedding_provider'],count=stats['vector_count'],consistent=stats['consistent'],projection=str(portable)),
                    boundary='隔离恢复已验证原文件摘要、SQLite 及向量投影；默认使用离线 hash 后端。实际嵌入模型需复用外部权重并以 vector_factory 单独演练，未切换运行中的数据库。')
                (root/'recovery-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                return result
            finally:vector.close()
        except Exception:
            (root/'INCOMPLETE.txt').write_text('Recovery failed; do not use this directory as a live workspace.',encoding='utf-8')
            raise
