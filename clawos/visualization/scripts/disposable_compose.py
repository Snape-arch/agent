"""Explicitly scoped Compose operations for disposable acceptance projects."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


class DisposableCompose:
    def __init__(self, project: str, files: list[str] | None = None):
        if not re.fullmatch(r'clawvision-(?:e2e|acceptance|soak|restore|chaos)(?:-[a-z0-9-]+)?', project):
            raise ValueError('an explicitly named clawvision acceptance/restore project is required')
        self.project = project
        self.command = ['docker', 'compose', '-p', project]
        for file in files or ['docker-compose.yml']:
            if not Path(file).is_file(): raise ValueError('Compose file not found')
            self.command.extend(['-f', str(Path(file).resolve())])

    def run(self, *args: str, **kwargs):
        options = {'check': True, 'timeout': 300, **kwargs}
        return subprocess.run([*self.command, *args], **options)

    def require_fresh(self):
        for kind in ('container', 'volume'):
            existing = subprocess.run(['docker', kind, 'ls', *(['--all'] if kind == 'container' else []), '--filter', f'label=com.docker.compose.project={self.project}',
                                       '--format', '{{.ID}}' if kind == 'container' else '{{.Name}}'],
                                      capture_output=True, text=True, check=True, timeout=30)
            if existing.stdout.strip(): raise ValueError('restore target must have no existing containers or volumes')
