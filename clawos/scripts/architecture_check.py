"""Check maintained boundaries and file budgets without loading application services."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re


APP = Path(__file__).resolve().parents[1]
FILE_BUDGETS = {
    'clawos_server.py': 2000,
    'application/routing.py': 1400,
    'application/execution.py': 1100,
    'memoryos/memory_store.py': 750,
    'workspace_services.py': 300,
    'agent_learning.py': 60,
    'visualization/backend/server.py': 800,
    'static/assets/console.js': 450,
}
DIRECTORY_BUDGETS = {
    'api': ('.py', 1000),
    'memoryos/repositories': ('.py', 1200),
    'services/workspace': ('.py', 650),
    'services/learning': ('.py', 650),
    'visualization/backend/handlers': ('.py', 650),
    'static/assets/console': ('.js', 1000),
}


def inspect_architecture(app: Path = APP) -> dict:
    budgets = dict(FILE_BUDGETS)
    for directory, (suffix, limit) in DIRECTORY_BUDGETS.items():
        budgets.update((path.relative_to(app).as_posix(), limit) for path in (app / directory).glob('*' + suffix))
    errors = []
    sizes = {}
    for name, limit in sorted(budgets.items()):
        path = app / name
        if not path.is_file():
            errors.append(f'Missing maintained source {name}')
            continue
        source = path.read_text(encoding='utf-8')
        sizes[name] = len(source.splitlines())
        if sizes[name] > limit:
            errors.append(f'{name} has {sizes[name]} lines, budget is {limit}')
        if path.suffix == '.js':
            if name.startswith('static/assets/console/'):
                imports = re.findall(r"^import\s+.*?from\s+['\"]([^'\"]+)['\"]", source, re.MULTILINE)
                if any(target != './core.js' for target in imports):
                    errors.append(f'{name} imports another feature instead of using composition actions')
            continue
        tree = ast.parse(source, filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports = [node.module or '']
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            else:
                continue
            if name.startswith(('api/', 'application/', 'memoryos/repositories/', 'services/workspace/', 'services/learning/', 'visualization/backend/handlers/')):
                if any(module in {'clawos_server', 'visualization.backend.server', 'workspace_services', 'agent_learning'} for module in imports):
                    errors.append(f'{name}:{node.lineno} imports its composition root')
            if name.startswith('memoryos/repositories/') and any(module.startswith(('api.', 'application.', 'providers.')) for module in imports):
                errors.append(f'{name}:{node.lineno} reverses the persistence dependency boundary')
    return {'passed': not errors, 'errors': errors, 'source_lines': sizes}


if __name__ == '__main__':
    report = inspect_architecture()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['passed'] else 1)
