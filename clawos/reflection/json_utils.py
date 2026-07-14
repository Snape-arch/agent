"""Small, exception-safe JSON helpers shared by reflection layers."""
from __future__ import annotations

import json
from typing import Any


def parse_json_value(value: Any) -> Any:
    """Parse a JSON string, preserving non-JSON values without hiding interrupts."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
