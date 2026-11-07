"""Non-destructive scene operations and bilingual natural-language command planning."""

from __future__ import annotations

import copy
import re
import uuid


COLORS = {"红": "#ef4444", "红色": "#ef4444", "blue": "#3b82f6", "蓝": "#3b82f6", "蓝色": "#3b82f6", "green": "#22c55e", "绿": "#22c55e", "黑": "#18181b", "白": "#f8fafc", "金": "#d4a72c", "银": "#a8b4c4"}


def _targets(plan: dict, requested) -> list[str]:
    names = [str(part.get("name", "")) for part in plan.get("parts", [])]
    if requested in (None, "", [], [""]): return names[:1]
    values = requested if isinstance(requested, list) else [requested]
    matched = []
    for value in values:
        needle = str(value).lower()
        matched.extend(name for name in names if needle == name.lower() or needle in name.lower())
    return list(dict.fromkeys(matched))


def apply_operations(plan: dict, operations: list[dict]) -> dict:
    result = copy.deepcopy(plan)
    for operation in operations:
        kind = str(operation.get("type") or "")
        targets = set(_targets(result, operation.get("targetIds")))
        payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
        if kind == "delete":
            result["parts"] = [part for part in result.get("parts", []) if part.get("name") not in targets]
            continue
        if kind == "duplicate":
            copies = []
            offset = payload.get("offset", [0.25, 0, 0])
            for part in result.get("parts", []):
                if part.get("name") in targets:
                    clone = copy.deepcopy(part); clone["name"] = str(part.get("name")) + " copy"
                    clone["position"] = [float(value) + float(offset[index] if index < len(offset) else 0) for index, value in enumerate(part.get("position", [0, 0, 0]))]
                    copies.append(clone)
            result.setdefault("parts", []).extend(copies); continue
        for part in result.get("parts", []):
            if part.get("name") not in targets: continue
            if kind == "transform":
                for field in ("position", "rotation", "size"):
                    if field not in payload: continue
                    value = payload[field]
                    if field == "size" and isinstance(value, (int, float)):
                        part[field] = [float(item) * float(value) for item in part.get(field, [1, 1, 1])]
                    elif payload.get("relative", True):
                        part[field] = [float(item) + float(value[index] if index < len(value) else 0) for index, item in enumerate(part.get(field, [0, 0, 0]))]
                    else: part[field] = [float(item) for item in value]
            elif kind == "material":
                for field in ("color", "material", "uv"):
                    if field in payload: part[field] = copy.deepcopy(payload[field])
            elif kind == "csg": part["booleanOperation"] = payload.get("operation", "union")
            elif kind == "group": part["groupId"] = str(payload.get("groupId") or "group")
            elif kind in {"remesh", "repair"}:
                part.setdefault("modifiers", []).append({"id": "mod_" + uuid.uuid4().hex[:8], "type": kind, **payload})
    return result


def _number(command: str, default: float = 1.0) -> float:
    matches = list(re.finditer(r"(-?\d+(?:\.\d+)?)\s*(mm|cm|m|%|度|°)?", command, re.I))
    if not matches: return default
    match = matches[-1]  # Node names such as "Arm 1" may contain an earlier index.
    value = float(match.group(1)); unit = (match.group(2) or "").lower()
    if unit == "mm": value /= 1000
    elif unit == "cm": value /= 100
    elif unit == "%": value /= 100
    elif unit in {"度", "°"}: value = value * 3.141592653589793 / 180
    return value


def _target_from_command(command: str, plan: dict) -> list[str]:
    names = [str(part.get("name", "")) for part in plan.get("parts", [])]
    direct = [name for name in names if name and name.lower() in command.lower()]
    if direct: return direct
    aliases = {"左": ("left", "左"), "右": ("right", "右"), "前": ("front", "前"), "后": ("rear", "back", "后"), "top": ("top", "upper", "上"), "底": ("bottom", "base", "底")}
    for token, needles in aliases.items():
        if token in command.lower() or any(needle in command.lower() for needle in needles):
            matched = [name for name in names if any(needle in name.lower() for needle in needles)]
            if matched: return matched
    return names[:1]


def interpret_scene_command(command: str, plan: dict) -> dict:
    command = command.strip()
    if not command or len(command) > 1000: raise ValueError("scene command must contain 1 to 1000 characters")
    targets = _target_from_command(command, plan); lower = command.lower(); value = _number(command)
    operations: list[dict] = []
    def add(kind: str, payload: dict): operations.append({"id": "op_" + uuid.uuid4().hex[:10], "type": kind, "targetIds": targets, "payload": payload})
    if any(word in lower for word in ("删除", "delete", "remove")): add("delete", {})
    elif any(word in lower for word in ("复制", "duplicate", "copy")): add("duplicate", {"offset": [value or .25, 0, 0]})
    elif any(word in lower for word in ("旋转", "rotate")):
        axis = 0 if "x" in lower else 2 if "z" in lower else 1; vector = [0.0, 0.0, 0.0]; vector[axis] = value
        add("transform", {"rotation": vector, "relative": True, "space": "local"})
    elif any(word in lower for word in ("放大", "缩小", "scale", "larger", "smaller")):
        factor = value if "%" not in command else 1 + value
        if any(word in lower for word in ("缩小", "smaller")): factor = max(.01, 1 - value)
        add("transform", {"size": factor or 1.1, "relative": True, "space": "local"})
    elif any(word in lower for word in ("移动", "move", "translate", "抬高", "降低")):
        axis = 0 if any(word in lower for word in ("x", "左右", "向左", "向右")) else 2 if any(word in lower for word in ("z", "前", "后")) else 1
        sign = -1 if any(word in lower for word in ("向左", "降低", "down", "left", "backward", "向后")) else 1
        vector = [0.0, 0.0, 0.0]; vector[axis] = sign * value
        add("transform", {"position": vector, "relative": True, "space": "world"})
    elif any(word in lower for word in ("挖孔", "打孔", "subtract", "布尔差")): add("csg", {"operation": "subtract"})
    elif any(word in lower for word in ("并集", "union")): add("csg", {"operation": "union"})
    elif any(word in lower for word in ("重拓扑", "减面", "remesh")): add("remesh", {"targetFaces": max(100, int(value))})
    elif any(word in lower for word in ("修复", "repair", "法线")): add("repair", {"normals": True, "holes": True})
    else:
        color = next((hex_value for name, hex_value in COLORS.items() if name in lower), None)
        material = next((name for name in ("metal", "wood", "glass") if name in lower), None)
        if color or material or any(word in lower for word in ("材质", "颜色", "color", "material")): add("material", {**({"color": color} if color else {}), **({"material": material} if material else {})})
    if not operations: raise ValueError("command is not yet recognized; name a node and request move, rotate, scale, material, CSG, duplicate, delete, remesh or repair")
    preview = apply_operations(plan, operations)
    return {"command": command, "operations": operations, "affectedNodeIds": targets, "previewPlan": preview, "explanation": f"Planned {len(operations)} non-destructive operation(s) for {', '.join(targets)}"}
