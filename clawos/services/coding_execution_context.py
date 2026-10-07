"""Shared, bounded source evidence for single and collaborating coding agents.

Only selected source files and resolved local imports are read. This is an
application read policy, not OS isolation or proof of semantic completeness.
"""
from __future__ import annotations

import ast
import copy
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


class CodingExecutionContext:
    SCHEMA = 'clawos.coding-execution-context.v1'
    MAX_FILE_BYTES = 128_000
    MAX_SOURCE_BYTES = 384_000
    SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.kt', '.c', '.cpp',
                '.h', '.hpp', '.cc', '.cs', '.rb', '.php', '.sh', '.ps1', '.html', '.css', '.scss',
                '.json', '.yaml', '.yml', '.toml', '.ini', '.md', '.sql', '.xml', '.txt'}
    INSTRUCTIONS = {'AGENTS.md', 'CLAUDE.md', 'CLAWOS.md'}

    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode()).hexdigest()

    @classmethod
    def policy(cls):
        return dict(schema=cls.SCHEMA, builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    analyzer_sha256=hashlib.sha256(Path(__file__).with_name('coding_context_service.py').read_bytes()).hexdigest())

    @staticmethod
    def safe_path(value):
        if not isinstance(value, str):
            raise ValueError('context paths must be relative strings')
        path = PurePosixPath(value)
        excluded = {'.git', 'tools', '.aws', '.codex', '.venv', 'venv', 'node_modules', 'output',
                    '__pycache__', '.secrets', '.ssh'}
        if (not value or len(value) > 400 or path.is_absolute() or str(path) != value
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in value)
                or any(p.casefold() in excluded or p.casefold().startswith('.env') or p == '..'
                       or p.endswith((' ', '.'))
                       or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p)
                       for p in path.parts)
                or (path.suffix.lower() in {'.json', '.yaml', '.yml', '.toml', '.txt'}
                    and re.search(r'(?i)(credential|secret|token|password|private[-_]?key)', path.name))
                or path.suffix.lower() not in CodingExecutionContext.SUFFIXES):
            raise ValueError('context path is outside the source read policy')
        return value

    @classmethod
    def read(cls, repo, relative):
        repo = Path(repo).resolve()
        path = repo / cls.safe_path(relative)
        path.resolve().relative_to(repo)
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
               for p in (path, *path.parents) if p != repo.parent):
            raise ValueError('context cannot follow symbolic links or junctions')
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > cls.MAX_FILE_BYTES:
            raise ValueError('context source must be text under 128 KB')
        data = path.read_bytes()
        if len(data) > cls.MAX_FILE_BYTES or b'\x00' in data:
            raise ValueError('context source exceeded its text limit')
        return data

    @staticmethod
    def git(repo, *args):
        result = subprocess.run(['git', *args], cwd=repo, capture_output=True,
                                encoding='utf-8', errors='strict', timeout=30)
        if result.returncode:
            raise ValueError('Git source inventory unavailable')
        return result.stdout

    @classmethod
    def inventory(cls, repo):
        rows = set(cls.git(repo, 'ls-files', '-z').split('\0'))
        rows.update(cls.git(repo, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
        result = []
        for rel in sorted(rows):
            try:
                cls.safe_path(rel)
                result.append(rel)
            except ValueError:
                continue
        return result

    @classmethod
    def targets(cls, repo, objective, focus_paths):
        """Bounded default selection; explicit missing files remain creatable."""
        inventory = cls.inventory(repo)
        if focus_paths:
            if not isinstance(focus_paths, list) or any(not isinstance(p, str) for p in focus_paths):
                raise ValueError('focus_paths must be a list of relative source paths')
            selected = set()
            for raw in focus_paths:
                rel = cls.safe_path(raw) if Path(raw).suffix else str(PurePosixPath(raw))
                matches = [p for p in inventory if p.startswith(rel + '/')]
                if matches:
                    selected.update(matches)
                else:
                    selected.add(cls.safe_path(raw))
            if len(selected) > 24:
                raise ValueError('coding focus expands beyond 24 writable files; narrow the task')
            return sorted(selected)
        tokens = set(re.findall(r'[a-z][a-z0-9_]*', objective.lower()))
        candidates = [p for p in inventory if Path(p).suffix.lower() not in {'.json','.yaml','.yml','.toml','.ini','.md','.txt'}
                      and not re.search(r'(^|/)(tests?|__tests__)(/|_)|(^|/)test_|\.(test|spec)\.', p)]
        return sorted(candidates, key=lambda p: (-len(tokens & set(re.findall(r'[a-z][a-z0-9_]*', p.lower()))), p))[:12]

    @staticmethod
    def local_imports(rel, text, inventory):
        """Python import resolution, including package-relative imports, not LSP."""
        if not rel.endswith('.py'):
            return []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        roots = [PurePosixPath('.')]
        parent = PurePosixPath(rel).parent
        roots.extend([parent, *parent.parents])
        resolved = set()
        for node in ast.walk(tree):
            modules = []
            search = roots
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    search = [parent]
                    for _ in range(node.level - 1):
                        search = [p.parent for p in search]
                base = node.module or ''
                modules = [base] + ['.'.join(filter(None, (base, a.name))) for a in node.names if a.name != '*']
            for module in modules:
                for root in search:
                    stem = root / module.replace('.', '/') if module else root
                    matches = [str(stem) + '.py', (stem / '__init__.py').as_posix()]
                    found = [p for p in matches if p in inventory and p != rel]
                    if found:
                        resolved.update(found)
                        break
        return sorted(resolved)

    @classmethod
    def build(cls, service, repo, objective, *, write_paths=None, focus_paths=None,
              read_only_paths=None, failure_context=None, max_chars=6000, semantic_graph=None):
        repo = service._repo(repo)
        if cls.policy() != LOADED_POLICY:
            raise RuntimeError('loaded context builder source changed')
        if type(max_chars) is not int or max_chars <= 0:
            raise ValueError('max_chars must be a positive integer')
        limit = max(4000, min(max_chars, 32_000))
        writes = sorted(set(write_paths if write_paths is not None else cls.targets(repo, objective, focus_paths)))
        if not writes or len(writes) > 24:
            raise ValueError('execution context needs 1..24 writable source paths')
        for p in writes:
            cls.safe_path(p)
        reads = sorted(set(read_only_paths or []) - set(writes))
        if len(reads) > 24:
            raise ValueError('execution context has too many explicit dependency paths')
        for p in reads:
            cls.safe_path(p)
        inventory = set(cls.inventory(repo))
        frames = []
        for frame in (failure_context or [])[:4]:
            try:
                rel = cls.safe_path(frame['path'])
                if rel in inventory:
                    frames.append(dict(path=rel, line=max(1, int(frame.get('line', 1))),
                                       test_index=frame.get('test_index'), source=frame.get('source', 'caller_diagnostic')))
                    if rel not in writes and rel not in reads:
                        reads.append(rel)
            except (ValueError, KeyError, TypeError):
                continue
        if len(writes) + len(reads) > 40:
            raise ValueError('declared source view exceeds 40 files; narrow the task')
        rows = []; edges = []; omitted = []; total = 0
        queue = [(p, 0, True) for p in writes + reads]
        seen = set()
        while queue and len(rows) < 40:
            rel, depth, explicit = queue.pop(0)
            if rel in seen:
                continue
            seen.add(rel)
            try:
                data = cls.read(repo, rel)
                if data is not None and total + len(data) > cls.MAX_SOURCE_BYTES:
                    raise ValueError('context source bytes exceed 384 KB')
                text = data.decode('utf-8-sig') if data is not None else ''
            except (ValueError, UnicodeError, OSError) as exc:
                if explicit:
                    raise ValueError('cannot build declared context path: ' + rel) from exc
                omitted.append(dict(path=rel, reason='unreadable_or_over_limit'));continue
            total += len(data or b'')
            symbols, imports = service._analyze(Path(rel), text)
            lines = text.splitlines()
            frame = next((f for f in frames if f['path'] == rel and f['line'] <= len(lines)), None)
            matching = [s for s in symbols if len(s['name']) > 2 and s['name'].lower() in objective.lower()]
            target = min(matching, key=lambda s: (s['kind']=='classdef', -len(s['name']), s['line']), default=None)
            start = max(1, frame['line'] - 8) if frame else max(1, (target['line'] if target else 1) - 2)
            content = '\n'.join(lines[start-1:start+39])[:1600]
            rows.append(dict(path=rel, access='write' if rel in writes else 'read_only',
                state='missing' if data is None else 'present', sha256=hashlib.sha256(data).hexdigest() if data is not None else '',
                bytes=len(data or b''), start_line=start, end_line=start + len(content.splitlines()) - 1,
                content=content, truncated=content != text, symbols=(matching + [s for s in symbols if s not in matching])[:12], imports=imports[:12]))
            if depth < 2:
                for dep in cls.local_imports(rel, text, inventory):
                    edges.append(dict(source=rel, target=dep, kind='python_import', verification='static_local_resolution'))
                    queue.append((dep, depth + 1, False))
        omitted.extend(dict(path=p, reason='file_count_limit') for p, _, _ in queue if p not in seen)
        instructions = []
        directories = {PurePosixPath('.')}
        for rel in writes:
            parent = PurePosixPath(rel).parent
            directories.update([parent, *parent.parents])
        instruction_paths = [(directory, (directory / name).as_posix())
            for directory in sorted(directories, key=lambda p: (len(p.parts), str(p)))
            for name in sorted(cls.INSTRUCTIONS) if (directory / name).as_posix() in inventory]
        if len(instruction_paths) > 12:
            raise ValueError('instruction hierarchy exceeds 12 files; narrow the task')
        for directory, rel in instruction_paths:
            data = cls.read(repo, rel)
            if data is None:
                raise ValueError('instruction disappeared during context capture')
            total += len(data)
            if total > cls.MAX_SOURCE_BYTES:
                raise ValueError('context source and instruction bytes exceed 384 KB')
            text = data.decode('utf-8-sig')
            instructions.append(dict(path=rel, scope=str(directory), trust='repository_input',
                sha256=hashlib.sha256(data).hexdigest(), content=text[:600], truncated=len(text)>600))
        body = dict(schema=cls.SCHEMA, policy=copy.deepcopy(LOADED_POLICY), objective=objective[:2000], revision=cls.git(repo, 'rev-parse', 'HEAD').strip(),
            scope=dict(write_paths=writes, read_paths=[r['path'] for r in rows],
                       read_only_paths=[r['path'] for r in rows if r['access']=='read_only']),
            code_evidence=rows, instruction_hierarchy=instructions, dependencies=edges[:100],
            failure_frames=frames, omitted=omitted[:24],
            selection_policy='explicit_scope_or_bounded_path_tokens; Python_imports_two_hops; not_complete_repository_analysis',
            budget=dict(max_chars=limit, source_bytes=total, estimated_tokens_policy='characters_divided_by_four_not_model_tokenizer'),
            trust_policy=dict(repository='untrusted_project_input', dependency_access='read_only',
                              os_isolation_claimed=False, semantic_completeness_claimed=False))
        # Shrink complete structured fields; never slice a serialized JSON packet.
        def size():
            return len(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))) + 180
        for field in ('content', 'symbols', 'imports'):
            for row in reversed(rows):
                if size() <= limit:break
                row[field] = row[field][:max(0, len(row[field]) - (size()-limit))] if field == 'content' else []
                row['truncated'] = True
                if field == 'content':row['end_line'] = row['start_line'] + len(row['content'].splitlines()) - 1
        for row in reversed(instructions):
            if size() <= limit:break
            row['content']='';row['truncated']=True
        if size() > limit:
            body['dependencies']=[];body['omitted']=[]
        if size() > limit:
            raise ValueError('context metadata exceeds budget; narrow the task')
        body['source_fingerprint'] = cls.digest({
            'sources':[{k:r[k] for k in ('path','access','state','sha256')} for r in rows],
            'instructions':[{k:r[k] for k in ('path','scope','sha256')} for r in instructions]})
        body['context_digest'] = cls.digest(body)
        return body

    @classmethod
    def verify(cls, repo, manifest):
        cls.verify_packet(manifest)
        body = manifest
        for row in body['code_evidence'] + body['instruction_hierarchy']:
            data = cls.read(repo, row['path'])
            actual = hashlib.sha256(data).hexdigest() if data is not None else ''
            if actual != row['sha256']:
                raise ValueError('execution context source drift: ' + row['path'])

    @classmethod
    def verify_packet(cls, manifest):
        body = copy.deepcopy(manifest)
        digest = body.pop('context_digest', None)
        if body.get('schema') != cls.SCHEMA or digest != cls.digest(body):
            raise ValueError('execution context evidence changed')

    @classmethod
    def present(cls, manifest, supplied_files):
        """Reference excerpts already supplied in full; preserve frozen evidence."""
        cls.verify_packet(manifest)
        view = copy.deepcopy(manifest)
        references = []
        for row in view['code_evidence']:
            text = supplied_files.get(row['path'])
            excerpt = row['content']
            if not isinstance(text, str) or not excerpt or excerpt not in text:
                continue
            references.append(dict(path=row['path'], offset=text.index(excerpt), length=len(excerpt),
                text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest()))
            row['content'] = ''
        if not references:
            return view
        result = dict(schema='clawos.coding-context-presentation.v1', context_digest=manifest['context_digest'],
            view=view, references=references,
            instruction='Referenced code excerpts are in the supplied source file fields at offset/length; do not treat an empty excerpt as an empty file.')
        result['presentation_digest'] = cls.digest(result)
        encoded = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        return result if len(encoded(result)) < len(encoded(manifest)) else copy.deepcopy(manifest)

    @classmethod
    def restore_presentation(cls, presentation, supplied_files):
        if presentation.get('schema') == cls.SCHEMA:
            cls.verify_packet(presentation)
            return copy.deepcopy(presentation)
        body = copy.deepcopy(presentation)
        digest = body.pop('presentation_digest', None)
        if body.get('schema') != 'clawos.coding-context-presentation.v1' or digest != cls.digest(body):
            raise ValueError('context presentation changed')
        view = body['view']
        for reference in body['references']:
            text = supplied_files[reference['path']]
            if hashlib.sha256(text.encode('utf-8')).hexdigest() != reference['text_sha256']:
                raise ValueError('referenced source text changed')
            row = next(r for r in view['code_evidence'] if r['path'] == reference['path'])
            row['content'] = text[reference['offset']:reference['offset'] + reference['length']]
        cls.verify_packet(view)
        if view['context_digest'] != body['context_digest']:
            raise ValueError('context presentation identity changed')
        return view

    @classmethod
    def assert_changes(cls, manifest, changes):
        for change in changes:
            if change.get('path') not in manifest['scope']['write_paths']:
                raise ValueError('patch exceeds execution context write scope')

    @classmethod
    def failure_context(cls, repo, tests):
        from .coding_contracts import CodingContracts
        def command(repo, *args, check=False):
            return subprocess.run(['git', *args], cwd=repo, capture_output=True, timeout=30)
        return [dict(frame, source='actual_failure_frame') for frame in CodingContracts.failure_context(repo, tests, cls.safe_path, command)]


LOADED_POLICY = CodingExecutionContext.policy()
