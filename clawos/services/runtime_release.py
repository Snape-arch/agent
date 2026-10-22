"""Startup source snapshot and current-disk drift, without config or user data."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import uuid


def core_ready(database, workspace, release, vector):
    return bool(database.get('reachable') and workspace and not release.get('restart_required',True)
                and vector.get('initialized') is True and vector.get('consistent') is True
                and not vector.get('fallback_reason'))


class RuntimeRelease:
    ROOTS=('api','services','memoryos','providers','reflection','security','mtclaw','static','skills','scripts')
    SUFFIXES={'.py','.js','.css','.html'}

    def __init__(self,root):
        self.root=Path(root).resolve();self.instance=uuid.uuid4().hex
        self._lock=threading.Lock();self._cache={}
        self.startup=self.snapshot();self.startup_commit=self.commit()

    def commit(self):
        try:
            p=subprocess.run(['git','rev-parse','HEAD'],cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=3)
            value=p.stdout.strip()
            return value if p.returncode==0 and len(value)==40 and all(c in '0123456789abcdef' for c in value) else ''
        except (OSError,subprocess.TimeoutExpired):return ''

    def snapshot(self):
        files=list(self.root.glob('*.py'))
        for name in self.ROOTS:
            folder=self.root/name
            if folder.is_dir():files.extend(p for p in folder.rglob('*') if p.suffix in self.SUFFIXES and '__pycache__' not in p.parts)
        rows={}
        with self._lock:
            for p in sorted(set(files)):
                if not p.exists():continue
                if self.root not in p.resolve().parents or p.is_symlink():raise ValueError('Release sources must remain inside the source root')
                stat=p.stat();key=str(p.relative_to(self.root)).replace('\\','/')
                stamp=(stat.st_mtime_ns,stat.st_size,stat.st_ctime_ns)
                old=self._cache.get(key)
                value=old[1] if old and old[0]==stamp else hashlib.sha256(p.read_bytes()).hexdigest()
                self._cache[key]=(stamp,value);rows[key]=value
        digest=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return dict(digest=digest,files=rows)

    def status(self):
        current=self.snapshot();before=self.startup['files'];after=current['files']
        changed=sorted(k for k in before.keys()|after.keys() if before.get(k)!=after.get(k))
        return dict(schema='clawos.runtime-release.v1',instance_id=self.instance,startup_commit=self.startup_commit,
                    startup_source_digest=self.startup['digest'],current_source_digest=current['digest'],restart_required=bool(changed),
                    changed_files=changed[:100],changed_count=len(changed),source_files=len(after),
                    boundary='Startup filesystem snapshot, not an attestation of every lazily imported module or external dependency. Model readiness is checked separately.')
