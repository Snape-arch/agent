"""Bounded role schemas and strict local validation for coding model answers.

Provider grammar support never replaces local checks, scope validation or tests.
No malformed answer is repaired by rewriting its JSON or guessing its meaning.
"""
from __future__ import annotations

import json
import math
import re


def text(limit=16000, *, minimum=0):
    return dict(type='string', minLength=minimum, maxLength=limit)


def array(items, maximum, minimum=0):
    return dict(type='array', items=items, minItems=minimum, maxItems=maximum)


def obj(properties, required=None):
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required,
                additionalProperties=False)


def schema_for(role, paths, *, grounded_targets=None):
    """Use only caller-authorized paths; dependencies remain read-only."""
    paths = sorted(set(paths))
    if not paths:raise ValueError('structured coding output needs an explicit write scope')
    path = dict(type='string', enum=paths)
    symbol = dict(type='string', pattern=r'^[A-Za-z_][A-Za-z_0-9]{0,79}$')
    if role == 'planner':
        identifier = dict(type='string', pattern=r'^[a-z][a-z0-9_-]{0,39}$')
        node = obj(dict(id=identifier, objective=text(2000, minimum=1),
                        write_paths=array(path, 24, 1), depends_on=array(identifier, 24)))
        return obj(dict(nodes=array(node, 24, 1)))
    if role == 'reviewer':
        return obj(dict(approved=dict(type='boolean'), reasons=array(text(1500), 8), risks=array(text(1500), 8)))
    if role == 'diagnostician':
        target = obj(dict(path=path, symbol=symbol))
        if grounded_targets:target['enum']=grounded_targets
        return obj(dict(hypothesis=text(1500, minimum=1), targets=array(target, 4, 1),
                        expected_test_effect=text(1500, minimum=1)))
    common = dict(path=path)
    changes = {'anyOf': [
        obj(common | dict(operation=dict(type='string', enum=['replace']), old_text=text(minimum=1), new_text=text())),
        obj(common | dict(operation=dict(type='string', enum=['create']), content=text(minimum=1))),
        obj(common | dict(operation=dict(type='string', enum=['hunks']),
            hunks=array(obj(dict(old_text=text(minimum=1), new_text=text())), 24, 1))),
    ]}
    if role == 'proposal':
        return obj(dict(changes=array(changes, 20, 1), test_commands=array(array(text(2048, minimum=1), 32, 1), 5, 1),
                        explanation=text(2000), confidence=dict(type='number', minimum=0, maximum=1)),
                   ['changes', 'test_commands'])
    return obj(dict(summary=text(2000), changes=array(changes, 24, 1)), ['changes'])


def response_format(role, schema):
    # Optional legacy explanation/summary fields remain optional. No implicit
    # retry with unconstrained output if the provider rejects this capability.
    name = re.sub(r'[^A-Za-z_0-9]', '_', role)[:40]
    return dict(type='json_schema', json_schema=dict(name='coding_' + name, schema=decoder_schema(schema), strict=False))


def decoder_schema(schema):
    """Avoid expanding nested bounded repetitions in provider grammar compilers.

    Fields, types, edit unions and path/target enums remain constrained. Full
    size/numeric/identifier bounds are enforced by validate(), never dropped
    from the authoritative local schema. Output/token caps also remain intact.
    """
    if isinstance(schema, list):return [decoder_schema(v) for v in schema]
    if isinstance(schema, dict):
        return {k:decoder_schema(v) for k,v in schema.items()
                if k not in {'maxLength','maxItems','minimum','maximum','pattern'}}
    return schema


def validate(value, schema, location='$'):
    """Validate the bounded subset emitted above, including ignored grammar rules."""
    if 'anyOf' in schema:
        for alternative in schema['anyOf']:
            try:
                validate(value, alternative, location)
                return
            except ValueError:pass
        raise ValueError(location + ': no authorized edit schema matches')
    kind = schema.get('type')
    matches = {'object':type(value) is dict, 'array':type(value) is list,
               'string':type(value) is str, 'boolean':type(value) is bool,
               'number':type(value) is int or (type(value) is float and math.isfinite(value))}
    if kind and not matches[kind]:raise ValueError(location + ': expected ' + kind)
    if 'enum' in schema and value not in schema['enum']:raise ValueError(location + ': unauthorized enum value')
    if kind == 'object':
        properties = schema['properties']
        if set(value)-set(properties):raise ValueError(location + ': unknown fields')
        if set(schema['required'])-set(value):raise ValueError(location + ': missing required fields')
        for key, child in value.items():validate(child, properties[key], location+'.'+key)
    elif kind == 'array':
        if not schema['minItems'] <= len(value) <= schema['maxItems']:raise ValueError(location + ': array bound exceeded')
        for i, child in enumerate(value):validate(child, schema['items'], location+f'[{i}]')
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 16000):raise ValueError(location + ': text bound exceeded')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):raise ValueError(location + ': invalid identifier')
    elif kind == 'number':
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):raise ValueError(location + ': number bound exceeded')


def parse(content, schema):
    if type(content) is not str or len(content.encode('utf-8')) > 128000:raise ValueError('coding answer must be bounded text')
    # Keep explicitly supported legacy whole-answer fences, never embedded prose.
    fence = re.fullmatch(r'```(?:json)?\s*(\{[\s\S]*\})\s*```', content.strip())
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:raise ValueError('duplicate JSON field: '+key)
            value[key] = child
        return value
    def constant(name):raise ValueError('non-finite JSON number: '+name)
    try:value = json.loads(fence.group(1) if fence else content, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError) as exc:raise ValueError('invalid JSON: '+str(exc)) from exc
    validate(value, schema)
    return value
