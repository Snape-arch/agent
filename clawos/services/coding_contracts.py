"""Caller-owned requirements, test bindings and narrowly declared AST repairs.

Test bindings describe evidence, not a proof that the caller's tests are complete.
The optional exact-type rule permits mechanical normalization only after an
actual failing assertion references the declared function. No model semantics
or arbitrary packages are inferred, and real tests still decide success.
"""
from __future__ import annotations

import ast
import copy
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
            if not isinstance(item, dict) or set(item) - {'id', 'statement', 'paths', 'test_indexes', 'rule'}:
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
        if set(paths) != {p for item in value for p in item['paths']}:
            raise ValueError('requirements must cover all authorized write paths')
        if sum(len(item['statement']) for item in value) > 8000:
            raise ValueError('combined caller requirements exceed 8000 characters')
        return copy.deepcopy(value)

    @staticmethod
    def select(requirements, paths):
        return copy.deepcopy([r for r in requirements if set(r['paths']) & set(paths)])

    @staticmethod
    def bind_plan(requirements, nodes):
        owners = {r['id']: [n['id'] for n in nodes if set(r['paths']) & set(n['write_paths'])] for r in requirements}
        for requirement in requirements:
            assigned = {p for n in nodes for p in n['write_paths'] if p in requirement['paths']}
            if assigned != set(requirement['paths']):
                raise ValueError('planner omitted required write paths: ' + requirement['id'])
        return owners

    @staticmethod
    def results(requirements, tests, digest):
        return [dict(id=r['id'], requirement_digest=digest(r), test_indexes=r['test_indexes'],
                     passed=all(i < len(tests) and tests[i].get('exit_code') == 0 for i in r['test_indexes']),
                     evidence_kind='caller_selected_command_exit_codes') for r in requirements]

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
                    start, end = (node.lineno, min(node.end_lineno, node.lineno + 100)) if node else (max(1, lineno-8), lineno+8)
                    snippet = '\n'.join(lines[start-1:end])[:6000]
                    calls = sorted({n.func.id if isinstance(n.func, ast.Name) else n.func.attr
                                    for n in ast.walk(node or tree) if isinstance(n, ast.Call)
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
