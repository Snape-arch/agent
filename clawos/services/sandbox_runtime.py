"""Owned, integrity-checked stdlib deployment; no ambient interpreter ACLs."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from .appcontainer_process import safe_tree
from .file_transactions import _file_lock, write_text

BASE = Path(__file__).resolve().parents[1]


def sandbox_storage():
    return Path(os.environ.get('CLAWOS_OUTPUT_DIR') or BASE / 'output').absolute() / 'sandbox'


def copy_runtime(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    source = safe_tree(Path(getattr(sys, '_base_executable', sys.executable)).parent)
    for pattern in ('python.exe', '*.dll', 'LICENSE*'):
        for path in source.glob(pattern):
            if path.is_file(): shutil.copy2(path, destination / path.name)
    for name in ('DLLs', 'Lib'):
        shutil.copytree(source / name, destination / name,
            ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', '*.pyc'))
    return str(source / 'python.exe')


def runtime_files(root):
    root = safe_tree(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


class SandboxRuntime:
    def __init__(self, root=None):
        self.root = Path(root or sandbox_storage() / 'deployment').absolute()
        self.config = self.root / 'deployment.json'

    def resolve(self):
        pending = self.root / 'setup-state.json'
        if pending.exists():
            safe_tree(self.root)
            state = json.loads(pending.read_text(encoding='utf-8'))
            if not isinstance(state,dict) or not (state.get('phase')=='complete' or state.get('cleanup_verified') is True):
                raise ValueError('interrupted runtime setup requires inspection: '+str(pending))
        if not self.config.exists(): return None
        safe_tree(self.root)
        if self.config.stat().st_size > 1024 * 1024: raise ValueError('runtime manifest is too large')
        data = json.loads(self.config.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('schema') != 'clawos.private-runtime.v1':
            raise ValueError('invalid runtime manifest')
        if not all(isinstance(data.get(key),str) for key in ('directory','profile','sid')) or not isinstance(data.get('files'),dict):
            raise ValueError('runtime manifest fields missing or invalid')
        runtime = self.root / data['directory']
        if runtime.parent != self.root or not runtime.name.startswith('runtime-'):
            raise ValueError('runtime path escaped owned deployment')
        if not data.get('files') or runtime_files(runtime) != data['files']:
            raise ValueError('private runtime integrity changed; setup required')
        from .windows_appcontainer_boundary import WindowsAppContainerBoundary
        if not str(data['profile']).startswith('ClawOS.Runtime.'):
            raise ValueError('profile is not an owned runtime deployment')
        boundary = WindowsAppContainerBoundary(data['profile'], runtime_dir=runtime)
        status = boundary.status()
        if not status.get('installed') or status.get('sid') != data['sid']:
            raise ValueError('owned runtime profile is missing or changed')
        return boundary

    def status(self):
        try:
            boundary = self.resolve()
            return dict(configured=boundary is not None, integrity_verified=boundary is not None,
                        runtime=str(boundary.runtime_dir) if boundary else None,
                        profile=boundary.profile_name if boundary else None,
                        production_sandbox_ready=False, languages=['python-stdlib'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return dict(configured=False, integrity_verified=False, error=str(exc),
                        production_sandbox_ready=False)

    def prepare(self, *, confirmed=False):
        if confirmed is not True: raise PermissionError('confirmed=true required for runtime setup')
        if os.name != 'nt': raise RuntimeError('private LPAC deployment requires Windows')
        self.root.mkdir(parents=True, exist_ok=True); safe_tree(self.root)
        with _file_lock(self.root / 'setup-lock'):
            existing = self.resolve()
            if existing: return dict(self.status(), created=False)
            runtime = self.root / ('runtime-' + uuid.uuid4().hex)
            profile = 'ClawOS.Runtime.' + uuid.uuid4().hex
            from .windows_appcontainer_boundary import WindowsAppContainerBoundary
            boundary = WindowsAppContainerBoundary(profile, runtime_dir=runtime)
            installed = None
            state_path = self.root / 'setup-state.json'
            state = dict(profile=profile,runtime=runtime.name,phase='copying',cleanup_verified=False)
            def checkpoint(): write_text(state_path,json.dumps(state,sort_keys=True))
            checkpoint()
            try:
                source = copy_runtime(runtime)
                if not (runtime / 'python.exe').is_file(): raise ValueError('trusted interpreter missing')
                state['phase']='installing'; checkpoint()
                installed = boundary.install(confirmed=True)
                if not installed.get('created'): raise RuntimeError('fresh owned profile required')
                state.update(phase='activating',sid=installed['sid']); checkpoint()
                data = dict(schema='clawos.private-runtime.v1', directory=runtime.name,
                            profile=profile, sid=installed['sid'], source_interpreter=source,
                            files=runtime_files(runtime), dependencies='stdlib only')
                write_text(self.config, json.dumps(data, sort_keys=True), create_only=True)
                state.update(phase='complete',cleanup_verified=True); checkpoint()
            except BaseException:
                clean = state['phase']=='copying'
                if installed and installed.get('created'):
                    clean=boundary.uninstall(confirmed=True).get('deleted') is True
                state.update(phase='failed',cleanup_verified=clean); checkpoint()
                # Preserve incomplete copied files for diagnosis, never activate them.
                raise
            return dict(self.status(), created=True)
