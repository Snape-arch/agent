"""One development entry point for the ClawOS product and its internal modules."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from project_layout import REPOSITORY_ROOT as ROOT, WEB_ROOT, VISUALIZATION_ROOT, ROUTER_ROOT


def check():
    errors = []
    required = [APP/'clawos_server.py', WEB_ROOT/'package.json', VISUALIZATION_ROOT/'worker.py',
                ROUTER_ROOT/'server.py', ROUTER_ROOT.parent/'LICENSE', VISUALIZATION_ROOT/'LICENSE']
    errors.extend('Missing product source: '+str(p.relative_to(ROOT)) for p in required if not p.is_file())
    modules = {p.stem for p in (VISUALIZATION_ROOT/'backend').glob('*.py')}
    for p in (VISUALIZATION_ROOT/'backend').glob('*.py'):
        try: tree = ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError as exc:
            errors.append(f'{p.relative_to(ROOT)}:{exc.lineno}: {exc.msg}'); continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module in modules:
                errors.append(f'{p.relative_to(ROOT)}:{node.lineno}: unqualified internal import {node.module}')
            if isinstance(node, ast.Import) and any(a.name in modules for a in node.names):
                errors.append(f'{p.relative_to(ROOT)}:{node.lineno}: unqualified internal import')
    raw = subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode('utf-8')
    files = [ROOT/p for p in set(raw.split('\0')) if p and (ROOT/p).is_file()]
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(('MTClaw-框架代码/','integrations/clawvision/')):
            errors.append('Legacy source root is still active: '+rel)
    for name in ['README.md','docs/README.md','docs/ARCHITECTURE.md','docs/DEVELOPMENT.md','docs/MAINTAINABILITY.md','docs/VISUALIZATION.md','docs/ROUTER.md','docs/ROADMAP.md']:
        p = ROOT/name
        if not p.is_file(): errors.append('Missing current documentation: '+name); continue
        for href in re.findall(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)',p.read_text(encoding='utf-8')):
            if href.startswith(('https:','http:','#','mailto:')): continue
            if not (p.parent/href.split('#')[0]).exists(): errors.append(f'{name}: broken local link {href}')
    print(json.dumps({'passed':not errors,'source_files':len(files),'errors':errors},ensure_ascii=False))
    return int(bool(errors))


def run(command, *, cwd=ROOT, env=None):
    return subprocess.run(command,cwd=cwd,env=env,check=False).returncode


def tests(component):
    if component == 'core': return run([sys.executable,str(APP/'scripts/run_regression.py'),'--pattern','test_*.py'])
    if component == 'web': return run(['node',str(WEB_ROOT/'node_modules/vitest/vitest.mjs'),'run','--maxWorkers=2'],cwd=WEB_ROOT)
    with tempfile.TemporaryDirectory(prefix='clawos-module-tests-') as folder:
        # Never inherit a user's database, provider config, proxy or model keys.
        from scripts.application_runtime import clean_environment
        env = clean_environment()
        env.update(PYTHONPATH=os.pathsep.join([str(APP),str(VISUALIZATION_ROOT/'sdk'),str(VISUALIZATION_ROOT/'runtime-libs'),str(APP/'output/vision-libs'),str(APP/'output/module-test-libs')]),
                   CLAWOS_SKIP_LOCAL_ENV='1',CLAWVISION_DATA_DIR=str(Path(folder)/'data'),CLAWVISION_OBJECT_DIR=str(Path(folder)/'objects'))
        command = [sys.executable,'-m','pytest',str(APP/'mtclaw/tests'),'-q','-o','cache_dir='+str(APP/'output/router-pytest-cache')] if component == 'router' else [sys.executable,'-m','unittest','discover','-s',str(VISUALIZATION_ROOT/'tests'),'-v']
        return run(command,env=env)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('check');commands.add_parser('build-web')
    test=commands.add_parser('test');test.add_argument('component',choices=['core','router','visualization','web','all'])
    args=parser.parse_args()
    if args.command=='check': return check()
    if args.command=='build-web': return run(['node',str(APP/'scripts/build_vision_frontend.mjs')])
    for component in ['core','router','visualization','web'] if args.component=='all' else [args.component]:
        result=tests(component)
        if result:return result
    return 0


if __name__=='__main__':raise SystemExit(main())
