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
 'clawos/static/academy.html','clawos/static/academy-lab.html','clawos/static/assets/research-domains.js',
 'clawos/services/vision_teaching.py','clawos/services/vision_teaching_api.py','clawos/services/vision_teaching_engine.py',
 'clawos/scripts/vision_teaching_acceptance.py','clawos/scripts/vision_teaching_replay.py',
 'clawos/tests/test_vision_teaching.py','clawos/tests/test_vision_visualizations.py','clawos/static/assets/academy-lab.js','clawos/static/assets/academy-vision-learning.js']


def sha(raw):return hashlib.sha256(raw).hexdigest()
def group(paths):
    values={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(set(paths))}
    return dict(count=len(values),files=values,sha256=sha(json.dumps(values,sort_keys=True,separators=(',',':')).encode()))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--original',type=Path);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():raise SystemExit('Use a new delivery evidence file')
    raw=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-co','--exclude-standard','-z','--','clawos/visualization','clawos/web'])
    source=[ROOT/p.decode() for p in raw.split(b'\0') if p]
    assets=[p for p in (ROOT/'clawos/static/vision').rglob('*') if p.is_file()]
    result=dict(algorithm='SHA256 of sorted path-to-raw-file-SHA256 JSON',source=group(source),assets=group(assets),bridge=group([ROOT/p for p in HELPERS]))
    manifest=json.loads((ROOT/'docs/third-party/vision/SOURCE_SNAPSHOT.json').read_text(encoding='utf-8'))
    if a.original:
        changed=[]
        for name,expected in manifest['files'].items():
            path=a.original/name
            if not path.is_file() or sha(path.read_bytes())!=expected:changed.append(name)
        result['original_recheck']=dict(files=len(manifest['files']),changed=changed,all_snapshot_source_unchanged=not changed)
        supplement=ROOT/'docs/third-party/vision/SOURCE_SUPPLEMENT.json'
        if supplement.is_file():
            extra=json.loads(supplement.read_text(encoding='utf-8'))['files']
            modified=[name for name,expected in extra.items() if not (a.original/name).is_file() or sha((a.original/name).read_bytes())!=expected]
            result['original_supplement_recheck']=dict(files=len(extra),changed=modified,all_supplement_source_unchanged=not modified)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:{k:v for k,v in value.items() if k!='files'} if key!='original_recheck' and isinstance(value,dict) else value for key,value in result.items()},ensure_ascii=False))


if __name__=='__main__':main()
