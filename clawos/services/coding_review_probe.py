"""Replay a reviewer's data-only Python counterexample in a strict task sandbox."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from . import coding_structured_output as structured


_HARNESS = """\
import importlib.util
import json
import sys
from pathlib import Path

def equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equal(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, dict):
        return (all(type(k) is str for k in actual) and actual.keys() == expected.keys()
                and all(equal(actual[k], expected[k]) for k in expected))
    return actual == expected

path = Path(probe['path']).resolve()
sys.path[:0] = [str(path.parent), str(Path.cwd())]
spec = importlib.util.spec_from_file_location('_clawos_review_subject', path)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)
value = getattr(subject, probe['function'])(*probe['args'])
match = equal(value, probe['expected'])
print('CLAWOS_REVIEW_MATCH' if match else 'CLAWOS_REVIEW_MISMATCH')
raise SystemExit(0 if match else 42)
"""


def command_for(probe, targets, read_file):
    path, function = probe['path'], probe['function']
    if path not in targets.get(probe['requirement_id'], []):
        raise ValueError('counterexample path is outside its changed caller requirement')
    source = read_file(path)
    if function.startswith('_') or not any(
        isinstance(node, ast.FunctionDef) and node.name == function for node in ast.parse(source).body
    ):
        raise ValueError('counterexample requires a public synchronous top-level function')
    # Reuse the structured decoder's duplicate-key and non-finite checks on
    # embedded JSON. A JSON round trip also rejects exponent overflow.
    args = structured.parse('{"value":' + probe['arguments_json'] + '}',
                            structured.obj(dict(value=structured.array({}, 8))))['value']
    expected = json.loads(canonical_value(probe['expected_json']))
    payload = json.dumps(dict(path=Path(path).as_posix(), function=function, args=args, expected=expected),
                         allow_nan=False, separators=(',', ':')).encode('ascii').hex()
    source = "import json\nprobe = json.loads(bytes.fromhex('" + payload + "'))\n" + _HARNESS
    encoded = source.encode('utf-8').hex()
    return ['python', '-B', '-X', 'utf8', '-c', "exec(bytes.fromhex('" + encoded + "'))"]


def canonical_value(value):
    decoded = structured.parse('{"value":' + value + '}', structured.obj(dict(value={})))['value']
    return json.dumps(decoded, allow_nan=False, sort_keys=True, separators=(',', ':'))


def classify(result):
    boundary = result.get('sandbox', {})
    if result.get('timed_out') or not all(boundary.get(field) is True for field in (
        'strict_boundary_verified', 'parent_token_verified', 'git_control_pointer_sealed', 'profile_and_grants_removed',
    )):
        return 'unverified'
    marker = result.get('stdout', '').splitlines()[-1:]
    if (result['exit_code'], marker) == (42, ['CLAWOS_REVIEW_MISMATCH']):
        return 'mismatch'
    if (result['exit_code'], marker) == (0, ['CLAWOS_REVIEW_MATCH']):
        return 'match'
    return 'unverified'
