"""Small JSON repair helpers for local model structured output."""
from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    start = raw.find("{")
    if start < 0:
        return raw
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    return raw[start:]


def repair_json_text(text: str) -> str:
    cleaned = extract_json_object(text)
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned.strip()


def loads_repaired_json(text: str) -> dict[str, Any]:
    repaired = repair_json_text(text)
    parsed = json.loads(repaired)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Expected JSON object", repaired, 0)
    return parsed
