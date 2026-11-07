"""Read shipped module graphs for static contracts after source extraction."""
import ast
from pathlib import Path
import re


APP = Path(__file__).resolve().parents[1]


def read_console_source():
    assets = APP / 'static/assets'
    pending = [assets / 'console.js']
    visited = set()
    sources = []
    while pending:
        path = pending.pop(0).resolve()
        if path in visited:
            continue
        if not path.is_relative_to(assets.resolve()):
            raise ValueError('Console imports must stay inside static assets')
        visited.add(path)
        source = path.read_text(encoding='utf-8')
        sources.append(source)
        pending.extend(path.parent / name for name in re.findall(r"from\s+['\"](\.[^'\"]+\.js)['\"]", source))
    return '\n'.join(sources)


def read_server_source():
    pending = [APP / 'clawos_server.py']
    visited = set()
    sources = []
    while pending:
        path = pending.pop(0)
        if path in visited:
            continue
        visited.add(path)
        source = path.read_text(encoding='utf-8')
        sources.append(source)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split('.')[0] in {'api', 'application'}:
                target = APP.joinpath(*node.module.split('.')).with_suffix('.py')
                if target.is_file():
                    pending.append(target)
    return '\n'.join(sources)
