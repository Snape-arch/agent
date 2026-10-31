"""Fingerprint the integrated source and product assets; optionally recheck the original snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HELPERS=['.gitignore','.gitattributes','desktop/build_desktop.ps1','clawos/clawos_server.py',
 'clawos/services/vision_runtime.py','clawos/services/vision_api.py','clawos/tests/test_vision_integration.py',
 'clawos/scripts/import_clawvision.py','clawos/scripts/build_vision_frontend.mjs',
 'clawos/scripts/vision_integration_acceptance.py','clawos/scripts/vision_delivery_audit.py',
 'clawos/static/academy.html','clawos/static/academy-lab.html','clawos/static/assets/research-domains.js']


def sha(raw):return hashlib.sha256(raw).hexdigest()
def group(paths):
    values={p.relative_to(ROOT).as_posix():sha(p.read_text(encoding='utf-8').encode()) for p in sorted(set(paths))}
    return dict(count=len(values),files=values,sha256=sha(json.dumps(values,sort_keys=True,separators=(',',':')).encode()))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--original',type=Path);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():raise SystemExit('Use a new delivery evidence file')
    raw=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-co','--exclude-standard','-z','--','integrations/clawvision'])
    source=[ROOT/p.decode() for p in raw.split(b'\0') if p]
    assets=[p for p in (ROOT/'clawos/static/vision').rglob('*') if p.is_file()]
    result=dict(algorithm='SHA256 of sorted path-to-UTF8-LF-SHA256 JSON',source=group(source),assets=group(assets),bridge=group([ROOT/p for p in HELPERS]))
    manifest=json.loads((ROOT/'integrations/clawvision/SOURCE_SNAPSHOT.json').read_text(encoding='utf-8'))
    if a.original:
        changed=[]
        for name,expected in manifest['files'].items():
            path=a.original/name
            if not path.is_file() or sha(path.read_bytes())!=expected:changed.append(name)
        result['original_recheck']=dict(files=len(manifest['files']),changed=changed,all_snapshot_source_unchanged=not changed)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:{k:v for k,v in value.items() if k!='files'} if key!='original_recheck' and isinstance(value,dict) else value for key,value in result.items()},ensure_ascii=False))


if __name__=='__main__':main()
