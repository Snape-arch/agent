"""Dependency-free compiler from an AI Studio plan to a tessellated OBJ mesh."""

from __future__ import annotations

import math
import base64
import json
import struct
from dataclasses import dataclass
from implicit_geometry import mesh_plan_csg


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]


def _grid_surface(rings: int, segments: int, point) -> Mesh:
    vertices = [point(row / rings, column / segments) for row in range(rings + 1) for column in range(segments)]
    faces: list[tuple[int, int, int]] = []
    for row in range(rings):
        for column in range(segments):
            next_column = (column + 1) % segments
            a = row * segments + column
            b = row * segments + next_column
            c = (row + 1) * segments + column
            d = (row + 1) * segments + next_column
            faces.extend(((a, c, b), (b, c, d)))
    return Mesh(vertices, faces)


def _sphere(size: list[float], segments: int) -> Mesh:
    rx, ry, rz = (size + [size[0], size[0]])[:3]
    return _grid_surface(max(8, segments // 2), segments, lambda v, u: (
        rx * math.cos((v - .5) * math.pi) * math.cos(u * math.tau),
        ry * math.sin((v - .5) * math.pi),
        rz * math.cos((v - .5) * math.pi) * math.sin(u * math.tau),
    ))


def _cylinder(size: list[float], segments: int) -> Mesh:
    radius_top, height, radius_bottom = (size + [size[0], size[0]])[:3]
    vertices = []
    for y, radius in ((-height / 2, radius_bottom), (height / 2, radius_top)):
        vertices.extend((radius * math.cos(i * math.tau / segments), y, radius * math.sin(i * math.tau / segments)) for i in range(segments))
    vertices.extend(((0, -height / 2, 0), (0, height / 2, 0)))
    bottom, top = segments * 2, segments * 2 + 1
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.extend(((i, segments + i, j), (j, segments + i, segments + j), (bottom, j, i), (top, segments + i, segments + j)))
    return Mesh(vertices, faces)


def _torus(size: list[float], segments: int) -> Mesh:
    major, minor = size[0], max(.01, size[1] if len(size) > 1 else size[0] * .2)
    return _grid_surface(max(8, segments // 3), segments, lambda v, u: (
        (major + minor * math.cos(v * math.tau)) * math.cos(u * math.tau),
        minor * math.sin(v * math.tau),
        (major + minor * math.cos(v * math.tau)) * math.sin(u * math.tau),
    ))


def _capsule(size: list[float], segments: int) -> Mesh:
    radius = size[0]
    cylinder = max(0.0, (size[1] if len(size) > 1 else radius * 2) - radius * 2)
    return _grid_surface(max(8, segments // 2), segments, lambda v, u: (
        radius * math.cos((v - .5) * math.pi) * math.cos(u * math.tau),
        radius * math.sin((v - .5) * math.pi) + (-cylinder / 2 if v < .5 else cylinder / 2),
        radius * math.cos((v - .5) * math.pi) * math.sin(u * math.tau),
    ))


def _box(size: list[float]) -> Mesh:
    x, y, z = (size + [size[0], size[0]])[:3]
    vertices = [(sx * x / 2, sy * y / 2, sz * z / 2) for sx, sy, sz in (
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    )]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (3, 7, 6), (3, 6, 2), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return Mesh(vertices, faces)


def _rotate(vertex: tuple[float, float, float], rotation: list[float]) -> tuple[float, float, float]:
    x, y, z = vertex
    rx, ry, rz = (rotation + [0, 0, 0])[:3]
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return x, y, z


def compile_obj(plan: dict, quality: str = "high") -> tuple[bytes, dict]:
    parts = plan.get("parts") if isinstance(plan.get("parts"), list) else []
    if not parts or len(parts) > 512:
        raise ValueError("plan must contain 1 to 512 parts")
    if any(part.get("booleanOperation") for part in parts if isinstance(part, dict)):
        resolution = {"standard": 24, "high": 34, "ultra": 46}.get(quality, 34)
        vertices, faces = mesh_plan_csg(plan, resolution)
        if not vertices or not faces:
            raise ValueError("CSG operation produced an empty mesh")
        lines = ["# ClawVision watertight SDF/CSG mesh", f"# quality={quality}", "o CSG_Result"]
        lines.extend(f"v {x:.7f} {y:.7f} {z:.7f}" for x, y, z in vertices)
        lines.extend(f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces)
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        return payload, {"quality": quality, "vertices": len(vertices), "faces": len(faces), "bytes": len(payload), "generator": "clawvision-sdf-csg-v1", "watertight": True}
    segments = {"standard": 24, "high": 48, "ultra": 72}.get(quality, 48)
    scale = max(.01, min(100.0, float(plan.get("parameters", {}).get("scale", 1))))
    lines = ["# ClawVision AI Studio generated mesh", f"# quality={quality}"]
    vertex_offset = 1
    vertex_count = face_count = 0
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        shape = str(part.get("shape") or "box")
        size = [max(.001, float(value)) for value in part.get("size", [1, 1, 1])]
        mesh = _sphere(size, segments) if shape == "sphere" else _cylinder(size, segments) if shape == "cylinder" else _torus(size, segments) if shape == "torus" else _capsule(size, segments) if shape == "capsule" else _box(size)
        position = [float(value) for value in part.get("position", [0, 0, 0])]
        rotation = [float(value) for value in part.get("rotation", [0, 0, 0])]
        lines.append(f"o part_{index}_{str(part.get('name') or shape).replace(' ', '_')}")
        for vertex in mesh.vertices:
            x, y, z = _rotate(vertex, rotation)
            px, py, pz = (position + [0, 0, 0])[:3]
            lines.append(f"v {(x + px) * scale:.7f} {(y + py) * scale:.7f} {(z + pz) * scale:.7f}")
        for a, b, c in mesh.faces:
            lines.append(f"f {a + vertex_offset} {b + vertex_offset} {c + vertex_offset}")
        vertex_offset += len(mesh.vertices)
        vertex_count += len(mesh.vertices)
        face_count += len(mesh.faces)
        if face_count > 500_000:
            raise ValueError("generated mesh exceeds 500000 faces")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return payload, {"quality": quality, "vertices": vertex_count, "faces": face_count, "bytes": len(payload), "generator": "clawvision-mesh-v1"}


def compile_gltf(plan: dict, quality: str = "high", binary: bool = False) -> tuple[bytes, dict]:
    obj, stats = compile_obj(plan, quality)
    vertices: list[tuple[float, float, float]] = []
    indices: list[int] = []
    for line in obj.decode("utf-8").splitlines():
        if line.startswith("v "):
            _, x, y, z = line.split()
            vertices.append((float(x), float(y), float(z)))
        elif line.startswith("f "):
            indices.extend(int(value.split("/")[0]) - 1 for value in line.split()[1:4])
    if not vertices or not indices:
        raise ValueError("mesh contains no exportable geometry")
    position_bytes = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
    while len(position_bytes) % 4:
        position_bytes += b"\0"
    mins = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    height = max(1e-9, maxs[1] - mins[1])
    uv_bytes = b"".join(struct.pack("<ff", .5 + math.atan2(vertex[2], vertex[0]) / math.tau, (vertex[1] - mins[1]) / height) for vertex in vertices)
    while len(uv_bytes) % 4:
        uv_bytes += b"\0"
    uv_offset = len(position_bytes)
    index_offset = uv_offset + len(uv_bytes)
    index_bytes = b"".join(struct.pack("<I", index) for index in indices)
    buffer = position_bytes + uv_bytes + index_bytes
    color = str(plan.get("parameters", {}).get("color", "#67e8bd")).lstrip("#")
    try:
        rgba = [int(color[index:index + 2], 16) / 255 for index in (0, 2, 4)] + [1]
    except (ValueError, IndexError):
        rgba = [.4, .9, .75, 1]
    document = {
        "asset": {"version": "2.0", "generator": "ClawVision glTF exporter"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": str(plan.get("name") or "AI model")}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0}]}],
        "materials": [{"name": str(plan.get("parameters", {}).get("material") or "Material"), "pbrMetallicRoughness": {"baseColorFactor": rgba, "metallicFactor": .65, "roughnessFactor": .35}}],
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
                        {"buffer": 0, "byteOffset": uv_offset, "byteLength": len(uv_bytes), "target": 34962},
                        {"buffer": 0, "byteOffset": index_offset, "byteLength": len(index_bytes), "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3", "min": mins, "max": maxs},
                      {"bufferView": 1, "componentType": 5126, "count": len(vertices), "type": "VEC2", "min": [0, 0], "max": [1, 1]},
                      {"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR", "min": [min(indices)], "max": [max(indices)]}],
    }
    if not binary:
        document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(buffer).decode("ascii")
        payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return payload, {**stats, "format": "gltf", "bytes": len(payload)}
    json_chunk = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    buffer += b"\0" * ((4 - len(buffer) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(buffer)
    payload = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + struct.pack("<I4s", len(buffer), b"BIN\0") + buffer
    return payload, {**stats, "format": "glb", "bytes": len(payload)}
