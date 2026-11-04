"""Offline, credential-free import of historical Vision business data into an empty store."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import uuid

BUSINESS = ('runs','metrics','events','artifacts','jobs','datasets','visualization_specs','model_assets',
 'studio_generations','studio_feedback','parameter_snapshots','agent_runs','agent_stages','agent_artifacts',
 'text3d_jobs','studio_scene_versions','model_scenes','model_scene_versions','model_operation_jobs',
 'asset_projects','asset_components','asset_releases','run_asset_links','geometry_jobs','scene_agent_runs',
 'scene_agent_decisions','training_jobs')
EXCLUDED = {'users','tenants','memberships','api_tokens','credential_refs','tenant_quotas','audit_logs',
 'schema_migrations','sqlite_sequence','tenant_usage'}
ACTIVE = {'queued','running','pending','retrying','cancel_requested','paused'}
OBJECT_KEYS = {'object_key','objectKey','binaryKey','thumbnail_key','checkpoint_key','input_image_key'}
SECRET_KEYS = re.compile(r'^(?:password(?:_hash)?|api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|credential(?:s|_ref)?|ciphertext|secret|token)$',re.I)
WEIGHTS = {'.gguf','.safetensors','.pt','.pth','.onnx','.ckpt','.pkl','.pickle'}

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def database_files(path):
    return {suffix:sha(Path(str(path)+suffix)) if Path(str(path)+suffix).exists() else None for suffix in ('','-wal')}

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def sanitize(value,counts):
    if isinstance(value,dict):
        result={}
        for k,v in value.items():
            if SECRET_KEYS.fullmatch(k):counts['redacted_fields']+=1;result[k]='[removed during local migration]'
            else:result[k]=sanitize(v,counts)
        return result
    if isinstance(value,list):return [sanitize(x,counts) for x in value]
    if isinstance(value,str):
        value,n=re.subn(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}', 'Bearer [removed]', value);counts['redacted_fields']+=n
        value,n=re.subn(r'\bsk-[A-Za-z0-9_-]{16,}', '[removed]', value);counts['redacted_fields']+=n
    return value

def object_keys(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in OBJECT_KEYS and isinstance(v,str) and v:yield v
            yield from object_keys(v)
    elif isinstance(value,list):
        for v in value:yield from object_keys(v)

def safe_object(root,key):
    if not isinstance(key,str) or not key or '\\' in key or ':' in key or Path(key).is_absolute() or '..' in Path(key).parts:
        raise ValueError('Historical object key is unsafe')
    p=(root/key).resolve(strict=True)
    if not p.is_relative_to(root.resolve()) or not p.is_file() or p.suffix.lower() in WEIGHTS or p.stat().st_size>32*1024*1024:
        raise ValueError('Historical object escapes the store or exceeds import bounds')
    return p

def migrate(source_root,target_root,backend_root,python=sys.executable):
    source_root=Path(source_root).resolve(strict=True);target_root=Path(target_root).resolve();backend_root=Path(backend_root).resolve(strict=True)
    original=source_root/'data/clawvision.db';objects=source_root/'data/objects';before=sha(original);files_before=database_files(original)
    if source_root==target_root or source_root.is_relative_to(target_root) or target_root.is_relative_to(source_root):raise ValueError('Source and destination must be separate')
    if target_root.exists():raise ValueError('Destination already exists; refusing to overwrite or merge live records')
    target_root.parent.mkdir(parents=True,exist_ok=True)
    stage=target_root.with_name('.'+target_root.name+'-migration-'+uuid.uuid4().hex);stage.mkdir()
    receipt=dict(schema='clawos.vision-migration.v1',created=datetime.now(timezone.utc).isoformat(),source_database_sha256=before,
                 source_files_sha256=files_before,tables={},objects={},excluded={},cancelled_active={},redacted_fields=0,owner='local-user',public_shares_disabled=True)
    try:
        env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC') if k in os.environ}
        env.update(PYTHONPATH=str(backend_root),PYTHONNOUSERSITE='1',PYTHONIOENCODING='utf-8',
                   CLAWVISION_DATA_DIR=str(stage/'data'),DATABASE_URL='sqlite:///'+str(stage/'data/clawvision.db'))
        subprocess.run([str(python),'-X','utf8','-c','from database import init_database;init_database()'],env=env,cwd=backend_root,check=True,capture_output=True,timeout=30)
        with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(stage/'data/clawvision.db')) as dst:
            src.row_factory=sqlite3.Row;src.execute('PRAGMA query_only=ON');src.execute('BEGIN')
            names={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            unknown=names-set(BUSINESS)-EXCLUDED
            if any(src.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0] for n in unknown):raise ValueError('Unmapped nonempty historical tables require an explicit migration')
            for table in sorted(names&EXCLUDED):receipt['excluded'][table]=src.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0]
            refs=set()
            for table in BUSINESS:
                if table not in names:continue
                cols=[r[1] for r in src.execute('PRAGMA table_info('+table+')')]
                available={r[1] for r in dst.execute('PRAGMA table_info('+table+')')}
                if set(cols)-available:raise ValueError('Historical columns have no destination mapping')
                rows=src.execute('SELECT '+','.join('"'+k+'"' for k in cols)+' FROM '+table).fetchall()
                if len(rows)>1000000:raise ValueError('Historical table exceeds import row budget')
                receipt['tables'][table]=dict(rows=len(rows),source_rows_sha256=hashlib.sha256(packed([dict(r) for r in rows]).encode()).hexdigest())
                for row in rows:
                    value=dict(row)
                    for key,item in value.items():
                        if key=='tenant_id':value[key]='default'
                        elif key=='share_token':value[key]=secrets.token_urlsafe(32)
                        elif isinstance(item,str):
                            try:decoded=json.loads(item)
                            except (ValueError,TypeError):value[key]=sanitize(item,receipt)
                            else:
                                decoded=sanitize(decoded,receipt);refs.update(object_keys(decoded));value[key]=packed(decoded)
                        if key in OBJECT_KEYS and isinstance(item,str) and item:refs.add(item)
                    if value.get('status') in ACTIVE:
                        receipt['cancelled_active'][table]=receipt['cancelled_active'].get(table,0)+1;value['status']='cancelled'
                        if 'cancel_requested' in value:value['cancel_requested']=1
                        if 'error_message' in value:value['error_message']='Historical job imported without resuming execution'
                    if table=='visualization_specs':value['is_public']=0
                    dst.execute('INSERT INTO '+table+'('+','.join('"'+k+'"' for k in cols)+') VALUES('+','.join('?' for _ in cols)+')',[value[k] for k in cols])
                receipt['tables'][table]['destination_rows']=dst.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            copied=set();total=0
            while refs-copied:
                key=sorted(refs-copied)[0];p=safe_object(objects,key);raw=p.read_bytes();total+=len(raw)
                if total>2*1024**3:raise ValueError('Historical objects exceed import total budget')
                origin_sha=hashlib.sha256(raw).hexdigest()
                if p.suffix.lower()=='.json':
                    value=sanitize(json.loads(raw),receipt);refs.update(object_keys(value));data=packed(value).encode()
                else:data=raw
                out=stage/'objects'/key;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
                if sha(p)!=origin_sha:raise ValueError('Historical object changed during migration')
                receipt['objects'][key]=dict(source_sha256=origin_sha,destination_sha256=sha(out),bytes=len(data));copied.add(key)
            if dst.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Imported foreign keys failed')
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Imported database integrity failed')
            dst.commit()
        if database_files(original)!=files_before:raise ValueError('Historical source database or WAL changed during migration')
        receipt.update(passed=True,object_count=len(copied),source_database_unchanged=True,resumed_jobs=0)
        (stage/'migration-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        # Never replace an existing destination. A failed import remains unpublished.
        if target_root.exists():raise ValueError('Destination appeared during migration')
        stage.rename(target_root)
        return receipt
    except BaseException:
        # Retain failure evidence for inspection; do not delete user data.
        (stage/'migration-failed.json').write_text(json.dumps(dict(passed=False,source_database_sha256=before)),encoding='utf-8')
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--target',required=True,type=Path);p.add_argument('--backend',required=True,type=Path)
    args=p.parse_args();r=migrate(args.source,args.target,args.backend)
    print(json.dumps(dict(passed=r['passed'],rows={k:v['rows'] for k,v in r['tables'].items()},objects=r['object_count'],redacted_fields=r['redacted_fields'],cancelled_active=r['cancelled_active'])))
if __name__=='__main__':main()
