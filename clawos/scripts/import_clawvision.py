"""Freeze an explicit local ClawVision source snapshot; never copies runtime data."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOTS = ('backend', 'src', 'sdk', 'workers', 'scripts', 'tests', 'examples', 'docs')
EXTENSIONS = {'.py', '.ts', '.tsx', '.css', '.html', '.json', '.md', '.txt', '.toml', '.yaml', '.yml', '.svg', '.csv', '.gltf'}
CONFIG = {'README.md','CHANGELOG.md','package.json','pnpm-lock.yaml','pnpm-workspace.yaml','pyproject.toml','index.html',
          'tsconfig.json','tsconfig.app.json','tsconfig.node.json','vite.config.ts','vitest.config.ts','playwright.config.ts','playwright.production.config.ts'}
SKIP = {'node_modules','output','data','dist','coverage','__pycache__','tools','weights'}


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument('--source',type=Path,required=True); ap.add_argument('--destination',type=Path,required=True)
    a = ap.parse_args(); source = a.source.resolve(); dest = a.destination.resolve()
    if dest.exists(): raise SystemExit('Destination must be new; never overwrite an integrated snapshot')
    if source == dest or source in dest.parents: raise ValueError('snapshot must be outside original source')
    files = []
    for path in source.iterdir():
        if path.is_file() and (path.name in CONFIG or path.name.startswith('requirements') and path.suffix=='.txt' or path.name.upper().startswith(('LICENSE','NOTICE'))): files.append(path)
    for folder in ROOTS:
        for path in (source/folder).rglob('*'):
            relative = path.relative_to(source)
            if path.is_file() and path.suffix.lower() in EXTENSIONS and not any(p in SKIP or p.startswith('.') for p in relative.parts):
                if path.is_symlink(): raise ValueError('source symlink not permitted')
                files.append(path)
    if len(files)>1000 or sum(p.stat().st_size for p in files)>40_000_000: raise ValueError('snapshot budget exceeded')
    # Git reports only filenames/status; never inspect credentials or runtime databases.
    head = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    status = subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True)
    hashes = {}
    for path in sorted(files):
        if path.stat().st_size>4_000_000: raise ValueError('source file too large')
        raw = path.read_bytes(); relative = path.relative_to(source); hashes[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
        target = dest/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
    for path in files:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=hashes[path.relative_to(source).as_posix()]: raise ValueError('source changed during import; preserve failed snapshot')
    manifest = dict(source='ClawVision local working-tree snapshot',base_commit=head,captured=datetime.now(timezone.utc).isoformat(),
        dirty_paths=len(status.splitlines()),source_is_clean_commit=False if status.strip() else True,files=hashes,
        boundary='Includes current tracked and untracked source; original worktree untouched. No source database, artifacts, credentials, node_modules or weights imported.')
    (dest/'SOURCE_SNAPSHOT.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=len(files),bytes=sum(p.stat().st_size for p in files),base_commit=head,dirty_paths=manifest['dirty_paths'])))


if __name__=='__main__': main()
