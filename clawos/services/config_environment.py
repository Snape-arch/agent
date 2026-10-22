"""Shared configuration placeholder rules, with no heavy service imports."""
import os
import re

_PATTERN=re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

def resolve_environment(value):
    if isinstance(value,str):
        return _PATTERN.sub(lambda m:os.environ.get(m.group(1),m.group(2) or m.group(0)),value)
    if isinstance(value,dict):return {k:resolve_environment(v) for k,v in value.items()}
    if isinstance(value,list):return [resolve_environment(v) for v in value]
    return value
