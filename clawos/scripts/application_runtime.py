"""Prepare and verify the pinned Windows application environment, without user config.

Only dependencies are installed. Models, external desktop tools and user databases
are never downloaded, copied or opened. A standard base CPython is still required.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
DEPLOYMENT = PROJECT / 'deployment'
RUNTIMES = PROJECT / 'output' / 'app-runtimes'
PROFILE = 'windows-py312'
MARKER = 'application-runtime.json'
ENV_KEYS = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP',
            'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES',
            'PROGRAMFILES(X86)', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}


def digest(path):
    with Path(path).open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256')
    return value.hexdigest()


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def text_digest(path):
    # Git's Windows checkout may use CRLF; dependency identity is LF-normalized.
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def clean_environment():
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEYS}
    env.update(PYTHONNOUSERSITE='1', PYTHONIOENCODING='utf-8',
               PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               ANONYMIZED_TELEMETRY='False', CLAWOS_SKIP_LOCAL_ENV='1',
               OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    return env


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_lock(deployment=DEPLOYMENT):
    lock = Path(deployment) / (PROFILE + '.lock.txt')
    provenance = json.loads((Path(deployment) / (PROFILE + '.lock.json')).read_text(encoding='utf-8'))
    if (provenance.get('lock_sha256') != text_digest(lock)
            or provenance.get('input_sha256') != text_digest(Path(deployment) / (PROFILE + '.in'))
            or provenance.get('test_requirements_sha256') != text_digest(Path(deployment).parent / 'requirements-test.txt')):
        raise ValueError('Application lock or dependency inputs changed; regenerate the lock')
    rows = {}
    for raw in lock.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})', line)
        if not match:
            raise ValueError('Invalid hash-locked requirement')
        name = normalized(match[1])
        if name in rows:
            raise ValueError('Duplicate locked distribution')
        rows[name] = match[2]
    if not rows or 'pip' not in rows:
        raise ValueError('Application lock is empty or lacks its installer')
    return lock, rows


def validate_inventory(expected, actual, prefix, system_packages, python_version, machine):
    """Pure validation also used for negative regression tests."""
    prefix = Path(prefix).resolve()
    if python_version[:2] != [3, 12] or machine.lower() not in {'amd64', 'x86_64'}:
        raise ValueError('This profile requires Windows x64 CPython 3.12')
    if system_packages:
        raise ValueError('System/user site packages are not permitted')
    found = {}
    for row in actual:
        name = normalized(row['name'])
        if name in found:
            raise ValueError('Duplicate installed distribution: ' + name)
        location = Path(row['location']).resolve()
        if prefix not in location.parents:
            raise ValueError('Distribution outside selected runtime: ' + name)
        found[name] = row['version']
    if found != expected:
        missing = sorted(expected.keys() - found.keys())
        extra = sorted(found.keys() - expected.keys())
        changed = sorted(k for k in expected.keys() & found.keys() if expected[k] != found[k])
        raise ValueError(f'Runtime dependency drift: missing={missing}, extra={extra}, changed={changed}')
    return found


def probe():
    lock, expected = load_lock()
    prefix = Path(sys.prefix).resolve()
    config = prefix / 'pyvenv.cfg'
    settings = dict(line.lower().split('=', 1) for line in
                    config.read_text(encoding='utf-8').splitlines() if '=' in line) if config.is_file() else {}
    settings = {k.strip(): v.strip() for k, v in settings.items()}
    system = sys.prefix == sys.base_prefix or settings.get('include-system-site-packages') != 'false'
    # An injected site directory without metadata must also fail closed.
    for entry in sys.path:
        path = Path(entry).resolve()
        if path.name.lower() in {'site-packages', 'dist-packages'} and prefix not in path.parents:
            system = True
    if sys.platform != 'win32' or not sys.flags.isolated:
        raise ValueError('Run this Windows profile with Python -I')
    actual = [dict(name=d.metadata['Name'], version=d.version,
                   location=str(Path(d.locate_file('')).resolve())) for d in metadata.distributions()]
    packages = validate_inventory(expected, actual, prefix, system, list(sys.version_info[:3]), platform.machine())
    # Exercise binary extensions as well as discovery. No app startup or model download.
    modules = ('fastapi', 'uvicorn', 'httpx', 'numpy', 'reportlab', 'matplotlib.mathtext', 'pypdf', 'pymupdf',
               'pdfplumber', 'openpyxl', 'docx', 'pptx', 'lxml.etree', 'lark_oapi',
               'chromadb', 'torch', 'transformers', 'sentence_transformers',
               'faster_whisper', 'tree_sitter_python', 'tree_sitter_javascript',
               'tree_sitter_typescript', 'tree_sitter_go', 'tree_sitter_rust',
               'tree_sitter_c', 'tree_sitter_cpp', 'tree_sitter_c_sharp')
    for name in modules:
        importlib.import_module(name)
    import torch
    if torch.tensor([2, 3], device='cpu').sum().item() != 5:
        raise ValueError('CPU tensor operation failed')
    return dict(schema='clawos.application-runtime.v1', profile=PROFILE,
                executable=str(Path(sys.executable).resolve()), prefix=str(prefix),
                executable_sha256=digest(sys.executable),
                base_executable_sha256=digest(sys._base_executable),
                python=list(sys.version_info[:3]), machine=platform.machine(),
                lock_sha256=text_digest(lock), packages=packages, imports=list(modules),
                system_site_packages=False, cpu_tensor_verified=True,
                installed_file_integrity_attested=False,
                optional_ocr_installed=False, models_bundled=False)


def child_probe(executable):
    result = subprocess.run([str(executable), '-I', str(Path(__file__).resolve()), 'probe'],
                            env=clean_environment(), capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise ValueError('Runtime probe failed: ' + result.stderr[-4000:])
    # A dependency may write an informational banner before our final JSON line.
    return json.loads(result.stdout.strip().splitlines()[-1])


def verify(executable):
    executable = Path(executable).resolve(strict=True)
    marker = executable.parent.parent / MARKER
    saved = json.loads(marker.read_text(encoding='utf-8'))
    actual = child_probe(executable)
    for key in ('schema', 'profile', 'executable', 'prefix', 'executable_sha256',
                'base_executable_sha256', 'python', 'machine', 'lock_sha256', 'packages'):
        if saved.get(key) != actual[key]:
            raise ValueError('Runtime receipt drift: ' + key)
    return actual


@contextmanager
def prepare_lock(root):
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'prepare.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def selected_runtime(root=RUNTIMES):
    pointer = json.loads((root / 'current.json').read_text(encoding='utf-8'))
    name = pointer.get('directory', '')
    if not re.fullmatch(r'windows-py312-[0-9a-f]{12}-[0-9a-f]{8}', name):
        raise ValueError('Invalid runtime selection')
    folder = (root / name).resolve(strict=True)
    if root.resolve() != folder.parent:
        raise ValueError('Runtime selection escaped deployment directory')
    executable = folder / 'Scripts' / 'python.exe'
    receipt = verify(executable)
    if pointer.get('lock_sha256') != receipt['lock_sha256']:
        raise ValueError('Selected runtime lock changed')
    return executable


def prepare(base_python):
    lock, _ = load_lock()
    base_python = Path(base_python).resolve(strict=True)
    info = subprocess.check_output([str(base_python), '-I', '-c',
        'import json,sys,platform;print(json.dumps([sys.platform,list(sys.version_info[:2]),platform.machine()]))'],
        env=clean_environment(), text=True, timeout=20)
    host, version, machine = json.loads(info)
    if host != 'win32' or version != [3, 12] or machine.lower() not in {'amd64', 'x86_64'}:
        raise ValueError('Base Python must be Windows x64 CPython 3.12')
    with prepare_lock(RUNTIMES):
        name = PROFILE + '-' + text_digest(lock)[:12] + '-' + uuid.uuid4().hex[:8]
        target = RUNTIMES / name
        # Unique target; never overwrite or recursively delete another runtime.
        target.mkdir()
        atomic_json(target / 'state.json', dict(status='preparing', lock_sha256=text_digest(lock)))
        try:
            with (target / 'install.log').open('wb') as log:
                for command in (
                    [str(base_python), '-I', '-m', 'venv', str(target)],
                    [str(target / 'Scripts/python.exe'), '-I', '-m', 'pip', '--isolated',
                     '--disable-pip-version-check', 'install', '--only-binary=:all:',
                     '--index-url', 'https://pypi.org/simple', '--require-hashes', '-r', str(lock)],
                    [str(target / 'Scripts/python.exe'), '-I', '-m', 'pip', '--isolated', 'check'],
                ):
                    subprocess.run(command, env=clean_environment(), stdout=log, stderr=log,
                                   check=True, timeout=1800)
            report = child_probe(target / 'Scripts/python.exe')
            atomic_json(target / MARKER, report)
            verify(target / 'Scripts/python.exe')
            atomic_json(target / 'state.json', dict(status='verified', lock_sha256=text_digest(lock)))
            atomic_json(RUNTIMES / 'current.json', dict(directory=name, lock_sha256=text_digest(lock)))
        except BaseException as exc:
            atomic_json(target / 'state.json', dict(status='failed', error=type(exc).__name__))
            raise
    return target / 'Scripts/python.exe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify', 'selected', 'probe'])
    parser.add_argument('--python', help='Base CPython 3.12 for prepare; selected venv executable for verify')
    parser.add_argument('--path-file', help='Write verified selected executable for the Windows launcher')
    args = parser.parse_args()
    try:
        if args.action == 'probe':
            print(json.dumps(probe()))
        elif args.action == 'prepare':
            if not args.python:
                parser.error('prepare requires --python')
            print(prepare(args.python))
        elif args.action == 'verify':
            if not args.python:
                parser.error('verify requires --python')
            print(json.dumps(verify(args.python)))
        else:
            selected = selected_runtime()
            if args.path_file:
                Path(args.path_file).write_text(str(selected) + '\n', encoding='utf-8')
            print(selected)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'Application runtime rejected: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
