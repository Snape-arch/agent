"""Caller-owned requirements, test bindings and narrowly declared AST repairs.

Test bindings describe evidence, not a proof that the caller's tests are complete.
The optional exact-type rule permits mechanical normalization only after an
actual failing assertion references the declared function. No model semantics
or arbitrary packages are inferred, and real tests still decide success.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import keyword
from pathlib import Path
import re


class CodingContracts:
    BUILTINS = {'int', 'float', 'str', 'bool', 'bytes', 'list', 'dict', 'tuple'}

    @classmethod
    def validate(cls, value, paths, commands):
        if value is None:
            return []
        if not isinstance(value, list) or not 1 <= len(value) <= 24:
            raise ValueError('requirements must contain 1..24 caller-owned entries')
        identifiers = set()
        for item in value:
            if not isinstance(item, dict) or set(item) - {'id', 'statement', 'paths', 'test_indexes', 'rule', 'clauses', 'interface'}:
                raise ValueError('invalid requirement fields')
            identifier = item.get('id')
            if not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', identifier) or identifier in identifiers:
                raise ValueError('requirements need unique bounded identifiers')
            identifiers.add(identifier)
            if not isinstance(item.get('statement'), str) or not 1 <= len(item['statement'].strip()) <= 2000:
                raise ValueError('requirement statement must be bounded and nonempty')
            scope, tests = item.get('paths'), item.get('test_indexes')
            if (not isinstance(scope, list) or not scope or not all(isinstance(p, str) for p in scope)
                    or len(set(scope)) != len(scope) or not set(scope) <= set(paths)
                    or not isinstance(tests, list) or not tests
                    or any(type(i) is not int or not 0 <= i < len(commands) for i in tests)
                    or len(set(tests)) != len(tests)):
                raise ValueError('requirement scope or verification command binding invalid')
            rule = item.get('rule')
            if rule is not None:
                if (not isinstance(rule, dict) or set(rule) != {'kind', 'function', 'parameter', 'builtin_type'}
                        or rule['kind'] != 'python_exact_type' or len(scope) != 1 or not scope[0].endswith('.py')
                        or not isinstance(rule['builtin_type'], str) or rule['builtin_type'] not in cls.BUILTINS
                        or not all(isinstance(rule[k], str) and re.fullmatch(r'[A-Za-z_]\w{0,79}', rule[k])
                                   for k in ('function', 'parameter'))):
                    raise ValueError('unsupported or malformed caller rule')
            clauses = item.get('clauses')
            if clauses is not None:
                if not isinstance(clauses, list) or not 1 <= len(clauses) <= 16:
                    raise ValueError('contract clauses must contain 1..16 entries')
                clause_ids = set()
                for clause in clauses:
                    if (not isinstance(clause, dict) or set(clause) != {'id', 'category', 'statement', 'test_indexes'}
                            or not isinstance(clause['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', clause['id'])
                            or clause['id'] in clause_ids or not isinstance(clause['category'], str) or clause['category'] not in
                            {'input','validation','output','ordering','mutation','dependency','edge_case','behavior'}
                            or not isinstance(clause['statement'], str) or not 1 <= len(clause['statement'].strip()) <= 1000
                            or not isinstance(clause['test_indexes'], list) or not clause['test_indexes']
                            or any(type(i) is not int or i not in tests for i in clause['test_indexes'])
                            or len(set(clause['test_indexes'])) != len(clause['test_indexes'])):
                        raise ValueError('invalid or unbound contract clause')
                    clause_ids.add(clause['id'])
                if {i for c in clauses for i in c['test_indexes']} != set(tests):
                    raise ValueError('contract clauses must cover all requirement verification commands')
            interface = item.get('interface')
            if interface is not None:
                if (not isinstance(interface, dict) or set(interface)-{'kind','function','parameters','keyword_only','positional_only','defaults','async'}
                        or interface.get('kind') != 'python_signature' or len(scope) != 1 or not scope[0].endswith('.py')
                        or not isinstance(interface.get('function'), str) or not re.fullmatch(r'[A-Za-z_]\w{0,79}', interface['function'])
                        or keyword.iskeyword(interface['function'])
                        or not isinstance(interface.get('parameters'), list) or len(interface['parameters']) > 32
                        or type(interface.get('async', False)) is not bool):
                    raise ValueError('invalid caller Python interface')
                for field in ('parameters','keyword_only','positional_only','defaults'):
                    names = interface.get(field, [])
                    if (not isinstance(names, list) or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z_]\w{0,79}', n) or keyword.iskeyword(n) for n in names)
                            or len(set(names)) != len(names)):
                        raise ValueError('invalid Python interface parameters')
                names = interface['parameters']
                if (not set(interface.get('keyword_only', [])) <= set(names) or
                        not set(interface.get('positional_only', [])) <= set(names) or
                        set(interface.get('keyword_only', [])) & set(interface.get('positional_only', [])) or
                        not set(interface.get('defaults', [])) <= set(names)):
                    raise ValueError('Python interface parameter kinds are inconsistent')
        interfaces = {}
        for item in value:
            interface = item.get('interface')
            if interface:
                spec = interface | {k:interface.get(k, []) for k in ('keyword_only','positional_only','defaults')} | {'async':interface.get('async', False)}
                identity = (item['paths'][0], interface['function'])
                if interfaces.setdefault(identity, spec) != spec:
                    raise ValueError('contradictory caller Python interfaces')
        if set(paths) != {p for item in value for p in item['paths']}:
            raise ValueError('requirements must cover all authorized write paths')
        if sum(len(item['statement']) + sum(len(c['statement']) for c in item.get('clauses', [])) for item in value) > 8000:
            raise ValueError('combined caller requirements exceed 8000 characters')
        return copy.deepcopy(value)

    @staticmethod
    def select(requirements, paths):
        return copy.deepcopy([r for r in requirements if set(r['paths']) & set(paths)])

    @staticmethod
    def diagnosis_targets(repo, frames, paths):
        """Bound Python targets to executed frames/calls, not every authorized file."""
        cited = set()
        for frame in frames:
            # A displayed function can also contain earlier passing calls. Use
            # calls spanning the actual failing line when that location exists.
            line = frame.get('line')
            found = None
            if type(line) is int:
                path = (Path(repo)/frame['path']).resolve()
                path.relative_to(Path(repo).resolve())
                tree = ast.parse(path.read_text(encoding='utf-8'))
                found = {n.func.id if isinstance(n.func,ast.Name) else n.func.attr
                    for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,(ast.Name,ast.Attribute))
                    and n.lineno<=line<=n.end_lineno}
            cited.update(found if found is not None else frame.get('called_symbols', []))
        targets = []
        for path in paths:
            if not path.endswith('.py'):
                continue
            source = (Path(repo) / path).read_text(encoding='utf-8')
            own_symbols = {f.get('symbol') for f in frames if f.get('path') == path}
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in cited | own_symbols:
                    target = dict(path=path, symbol=node.name)
                    if target not in targets:
                        targets.append(target)
        return targets

    @staticmethod
    def bind_plan(requirements, nodes):
        owners = {r['id']: [n['id'] for n in nodes if set(r['paths']) & set(n['write_paths'])] for r in requirements}
        for requirement in requirements:
            assigned = {p for n in nodes for p in n['write_paths'] if p in requirement['paths']}
            if assigned != set(requirement['paths']):
                raise ValueError('planner omitted required write paths: ' + requirement['id'])
        return owners

    @staticmethod
    def checklist(requirements):
        rows = []
        for requirement in requirements:
            clauses = requirement.get('clauses') or [dict(id=requirement['id'], category='behavior',
                statement=requirement['statement'], test_indexes=requirement['test_indexes'])]
            for clause in clauses:
                rows.append(dict(requirement_id=requirement['id'], clause_id=clause['id'], category=clause['category'],
                    original_statement=requirement['statement'], statement=clause['statement'],
                    paths=requirement['paths'], test_indexes=clause['test_indexes'], interface=requirement.get('interface')))
        return copy.deepcopy(rows)

    @staticmethod
    def prompt_guidance(requirements):
        """General language semantics; never infer new caller constraints."""
        if not any(p.endswith('.py') for r in requirements for p in r['paths']):
            return ''
        return (
            ' Review every declared Python contract clause before proposing code. '
            'When the caller requires exact built-in types, isinstance accepts subclasses '
            'and bool is an int subclass: use type(value) is T or an explicit tuple of '
            'allowed built-in types for those exact checks. Check container and element '
            'types separately, before coercion. Do not impose exact-type constraints '
            'when the caller permits subclasses. Preserve the declared signature, '
            'validation failures, output types, ordering, duplicates and non-mutation '
            'requirements. Passing example tests does not establish all boundary cases.'
        )

    @staticmethod
    def interface_results(repo, requirements, *, overrides=None):
        rows = []
        for requirement in requirements:
            interface = requirement.get('interface')
            if not interface:continue
            rel = requirement['paths'][0]
            path = Path(repo)/rel; root = Path(repo).resolve()
            path.resolve().relative_to(root)
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
                raise ValueError('interface source cannot follow symbolic links')
            source = (overrides or {}).get(rel)
            if source is None:source = path.read_text(encoding='utf-8') if path.is_file() else ''
            if len(source.encode('utf-8')) > 128000:raise ValueError('interface source exceeds read bound')
            actual = None
            try:
                nodes = [n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name==interface['function']]
                if len(nodes)==1:
                    node = nodes[0]; args = node.args
                    actual = dict(kind='python_signature', function=node.name,
                        parameters=[a.arg for a in args.posonlyargs+args.args+args.kwonlyargs],
                        positional_only=[a.arg for a in args.posonlyargs], keyword_only=[a.arg for a in args.kwonlyargs],
                        defaults=[a.arg for a in (args.posonlyargs+args.args)[-len(args.defaults):]] if args.defaults else [],
                        **{'async':isinstance(node, ast.AsyncFunctionDef)})
                    actual['defaults'] += [a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None]
                    if args.vararg or args.kwarg:actual = None
            except SyntaxError:pass
            expected = dict(kind='python_signature', function=interface['function'], parameters=interface['parameters'],
                positional_only=interface.get('positional_only', []), keyword_only=interface.get('keyword_only', []),
                defaults=interface.get('defaults', []), **{'async':interface.get('async', False)})
            rows.append(dict(requirement_id=requirement['id'], path=rel, expected=expected, actual=actual,
                source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(), passed=actual==expected,
                evidence_kind='static_python_signature_only'))
        return rows

    @staticmethod
    def results(requirements, tests, digest, *, repo=None):
        if any(r.get('interface') for r in requirements) and repo is None:
            raise ValueError('interface verification requires actual owned source')
        interfaces = {row['requirement_id']:row for row in CodingContracts.interface_results(repo, requirements)} if repo is not None else {}
        rows = []
        for r in requirements:
            row = dict(id=r['id'], requirement_digest=digest(r), test_indexes=r['test_indexes'],
                passed=all(i < len(tests) and tests[i].get('exit_code') == 0 for i in r['test_indexes']),
                evidence_kind='caller_selected_command_exit_codes')
            if r.get('clauses'):
                row['clauses'] = [dict(id=c['id'], clause_digest=digest(c), category=c['category'], test_indexes=c['test_indexes'],
                    passed=all(i < len(tests) and tests[i].get('exit_code') == 0 for i in c['test_indexes']),
                    evidence_kind='caller_selected_command_exit_codes') for c in r['clauses']]
                row['passed'] = row['passed'] and all(c['passed'] for c in row['clauses'])
            if r['id'] in interfaces:
                row['interface'] = interfaces[r['id']]
                row['passed'] = row['passed'] and interfaces[r['id']]['passed']
            rows.append(row)
        return rows

    @staticmethod
    def failure_context(repo, tests, safe_path, git):
        """Bounded snippets from real tracebacks, only tracked files in this repo."""
        repo = Path(repo).resolve()
        result = []
        seen = set()
        for index, test in enumerate(tests):
            if test.get('exit_code') == 0:
                continue
            for name, line in re.findall(r'File "([^"\n]+)", line (\d+)', str(test.get('stderr', ''))[-20000:]):
                try:
                    path = Path(name)
                    path = path if path.is_absolute() else repo / path
                    rel = path.resolve().relative_to(repo).as_posix()
                    safe_path(rel)
                    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != repo.parent):
                        continue
                    if not rel.endswith('.py') or path.stat().st_size > 128000:
                        continue
                    if git(repo, 'ls-files', '--error-unmatch', '--', rel, check=False).returncode:
                        continue
                    lineno = int(line)
                    identity = (index, rel, lineno)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    text = path.read_text(encoding='utf-8')
                    tree = ast.parse(text)
                    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and n.lineno <= lineno <= n.end_lineno]
                    node = min(functions, key=lambda n: n.end_lineno - n.lineno) if functions else None
                    lines = text.splitlines()
                    if not 1 <= lineno <= len(lines):
                        continue
                    start = max(node.lineno, lineno-50) if node else max(1, lineno-8)
                    end = min(node.end_lineno, start+100) if node else lineno+8
                    snippet = '\n'.join(lines[start-1:end])[:6000]
                    calls = sorted({n.func.id if isinstance(n.func, ast.Name) else n.func.attr
                                    for n in ast.walk(node or tree) if isinstance(n, ast.Call)
                                    and start <= n.lineno <= end
                                    and isinstance(n.func, (ast.Name, ast.Attribute))})
                    result.append(dict(test_index=index, path=rel, line=lineno, start_line=start,
                                       symbol=node.name if node else '', snippet=snippet, called_symbols=calls,
                                       access='read_only_actual_failure'))
                    if len(result) == 4:
                        return result
                except (OSError, ValueError, SyntaxError):
                    continue
        return result

    @classmethod
    def exact_type_repair(cls, repo, requirements, tests, failure_context, read_files):
        changes, diagnostics = [], []
        used_paths = set()
        for requirement in requirements:
            rule = requirement.get('rule') or {}
            if rule.get('kind') != 'python_exact_type':
                continue
            failing = {i for i in requirement['test_indexes'] if tests[i].get('exit_code') != 0}
            if not any(frame['test_index'] in failing and rule['function'] in frame['called_symbols'] for frame in failure_context):
                continue
            path = requirement['paths'][0]
            if path in used_paths:
                continue
            text = read_files(repo, [path])[path]
            if text is None:
                continue
            tree = ast.parse(text)
            protected = {'type', 'isinstance', rule['builtin_type']}
            bound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            bound |= {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
            bound |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))}
            bound |= {a.asname or a.name.split('.')[0] for n in ast.walk(tree)
                      if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            if bound & protected:
                continue
            functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == rule['function']]
            if len(functions) != 1:
                continue
            function = functions[0]
            args = function.args.posonlyargs + function.args.args + function.args.kwonlyargs
            if rule['parameter'] not in {a.arg for a in args}:
                continue
            # Local rebinding, nested functions/lambdas and comprehensions can
            # change the name's meaning; refuse rather than speculate.
            if (any(isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not function
                    for n in ast.walk(function))
                    or any(isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.id == rule['parameter']
                           for n in ast.walk(function))):
                continue
            calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == 'isinstance' and not n.keywords and len(n.args) == 2
                     and isinstance(n.args[0], ast.Name) and n.args[0].id == rule['parameter']
                     and isinstance(n.args[1], ast.Name) and n.args[1].id == rule['builtin_type']]
            if not calls:
                continue
            data = text.encode('utf-8'); lines = data.splitlines(keepends=True)
            offsets = [0]
            for line in lines:
                offsets.append(offsets[-1]+len(line))
            begin = offsets[function.lineno-1]+function.col_offset
            end = offsets[function.end_lineno-1]+function.end_col_offset
            original = data[begin:end]; updated = original
            for call in sorted(calls, key=lambda n: (n.lineno, n.col_offset), reverse=True):
                a = offsets[call.lineno-1]+call.col_offset-begin
                b = offsets[call.end_lineno-1]+call.end_col_offset-begin
                replacement = f'(type({rule["parameter"]}) is {rule["builtin_type"]})'.encode()
                updated = updated[:a]+replacement+updated[b:]
            if original == updated:
                continue
            changes.append(dict(path=path, operation='replace', old_text=original.decode(), new_text=updated.decode()))
            diagnostics.append(dict(requirement_id=requirement['id'], path=path, function=rule['function'],
                                    parameter=rule['parameter'], builtin_type=rule['builtin_type'], occurrences=len(calls)))
            used_paths.add(path)
        return dict(summary='Normalize caller-declared exact builtin guards', changes=changes, diagnostics=diagnostics) if changes else None
