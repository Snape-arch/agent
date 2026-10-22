"""Convert a pip dry-run report to a reviewed Windows wheel-only hash lock.

Resolve in CPython 3.12 with --ignore-installed --only-binary=:all: and an explicit
https://pypi.org/simple index. This converter refuses direct/VCS/local artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse, unquote

DEPLOYMENT = Path(__file__).resolve().parents[1] / 'deployment'


def sha(path):
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def convert(report, deployment=DEPLOYMENT):
    env = report['environment']
    if (env['python_version'] != '3.12' or env['sys_platform'] != 'win32'
            or env['platform_machine'].lower() != 'amd64'):
        raise ValueError('Resolve on Windows x64 CPython 3.12')
    rows = {}
    for item in report['install']:
        info = item['download_info']
        url = urlparse(info['url'])
        filename = unquote(url.path.rsplit('/', 1)[-1])
        if (url.scheme != 'https' or url.hostname != 'files.pythonhosted.org'
                or url.username or url.password or url.query or url.fragment
                or not filename.endswith('.whl') or item.get('is_direct')):
            raise ValueError('Only PyPI HTTPS wheels without credentials are allowed')
        name = re.sub(r'[-_.]+', '-', item['metadata']['name']).lower()
        version = item['metadata']['version']
        digest = info['archive_info']['hashes']['sha256']
        if (not re.fullmatch(r'[a-z0-9-]+', name) or not re.fullmatch(r'[A-Za-z0-9.+!_-]+', version)
                or not re.fullmatch(r'[0-9a-f]{64}', digest) or name in rows):
            raise ValueError('Invalid or duplicate locked distribution')
        rows[name] = dict(version=version, sha256=digest, wheel=filename, url=info['url'])
    if 'pip' not in rows or len(rows) < 25:
        raise ValueError('Incomplete application dependency resolution')
    path = Path(deployment) / 'windows-py312.lock.txt'
    text = '# Generated from a Windows x64 CPython 3.12 pip report. Do not edit.\n'
    text += ''.join(f'{name}=={row["version"]} --hash=sha256:{row["sha256"]}\n' for name, row in sorted(rows.items()))
    path.write_text(text, encoding='utf-8', newline='\n')
    provenance = dict(schema='clawos.application-lock.v1', python='3.12', platform='win_amd64',
        input_sha256=sha(Path(deployment) / 'windows-py312.in'),
        test_requirements_sha256=sha(Path(deployment).parent / 'requirements-test.txt'),
        lock_sha256=sha(path), pip_version=report['pip_version'], packages=rows,
        boundary='Wheel hashes verify downloads. Base CPython, external desktop tools, models and optional PaddleOCR are separate.')
    path.with_suffix('.json').write_text(json.dumps(provenance, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return dict(packages=len(rows), lock_sha256=provenance['lock_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    args = parser.parse_args()
    print(json.dumps(convert(json.loads(Path(args.report).read_text(encoding='utf-8')))))
