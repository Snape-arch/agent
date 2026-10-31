"""Deterministic geometry and packaging quality gates for generated 3D assets."""

from __future__ import annotations

import json
import math
import struct

from mesh_postprocess import parse_obj


def _obj_report(payload: bytes) -> dict:
    vertices, faces = parse_obj(payload)
    degenerate = 0
    edges: dict[tuple[int, int], int] = {}
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(vertices))}
    for a, b, c in faces:
        va, vb, vc = vertices[a], vertices[b], vertices[c]
        cross = (
            (vb[1] - va[1]) * (vc[2] - va[2]) - (vb[2] - va[2]) * (vc[1] - va[1]),
            (vb[2] - va[2]) * (vc[0] - va[0]) - (vb[0] - va[0]) * (vc[2] - va[2]),
            (vb[0] - va[0]) * (vc[1] - va[1]) - (vb[1] - va[1]) * (vc[0] - va[0]),
        )
        if math.sqrt(sum(value * value for value in cross)) < 1e-9:
            degenerate += 1
        for left, right in ((a, b), (b, c), (c, a)):
            edge = tuple(sorted((left, right))); edges[edge] = edges.get(edge, 0) + 1
            adjacency[left].add(right); adjacency[right].add(left)
    boundary = sum(count == 1 for count in edges.values())
    non_manifold = sum(count > 2 for count in edges.values())
    active = {index for face in faces for index in face}; components = 0
    while active:
        components += 1; stack = [active.pop()]
        while stack:
            for neighbor in adjacency[stack.pop()]:
                if neighbor in active: active.remove(neighbor); stack.append(neighbor)
    score = 45
    score += 15 if degenerate == 0 else max(0, 15 - round(degenerate / max(1, len(faces)) * 100))
    score += 15 if non_manifold == 0 else 0
    score += 10 if boundary == 0 else 5
    score += 10 if components == 1 else max(0, 10 - components)
    score += 5 if len(vertices) >= 100 else 2
    issues = []
    if degenerate: issues.append(f"{degenerate} degenerate triangles")
    if non_manifold: issues.append(f"{non_manifold} non-manifold edges")
    if boundary: issues.append(f"{boundary} open boundary edges")
    if components > 1: issues.append(f"{components} disconnected components")
    return {"format": "obj", "score": min(100, score), "metrics": {"vertices": len(vertices), "faces": len(faces), "degenerateFaces": degenerate, "boundaryEdges": boundary, "nonManifoldEdges": non_manifold, "components": components}, "issues": issues}


def _glb_document(payload: bytes) -> dict:
    if len(payload) < 20 or payload[:4] != b"glTF":
        raise ValueError("invalid GLB header")
    _, version, declared = struct.unpack_from("<4sII", payload)
    if version != 2 or declared != len(payload):
        raise ValueError("invalid GLB version or byte length")
    json_length, kind = struct.unpack_from("<I4s", payload, 12)
    if kind != b"JSON" or 20 + json_length > len(payload):
        raise ValueError("missing GLB JSON chunk")
    return json.loads(payload[20:20 + json_length].decode("utf-8").rstrip(" \0"))


def validate_gltf_contract(document: dict) -> dict:
    """Validate reference integrity that render-only smoke tests tend to miss."""
    issues: list[str] = []
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    buffers = document.get("buffers", [])
    materials = document.get("materials", [])
    textures = document.get("textures", [])
    images = document.get("images", [])
    for index, accessor in enumerate(accessors):
        view = accessor.get("bufferView")
        if view is not None and (not isinstance(view, int) or view < 0 or view >= len(views)):
            issues.append(f"accessor {index} references missing bufferView")
        bounds = [accessor.get("min"), accessor.get("max")]
        if any(isinstance(items, list) and any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in items) for items in bounds):
            issues.append(f"accessor {index} contains non-finite bounds")
    for index, view in enumerate(views):
        buffer_index = view.get("buffer", 0)
        if not isinstance(buffer_index, int) or buffer_index < 0 or buffer_index >= len(buffers):
            issues.append(f"bufferView {index} references missing buffer")
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            references = list(primitive.get("attributes", {}).values())
            if primitive.get("indices") is not None:
                references.append(primitive["indices"])
            if any(not isinstance(ref, int) or ref < 0 or ref >= len(accessors) for ref in references):
                issues.append(f"mesh {mesh_index} primitive {primitive_index} references missing accessor")
            material = primitive.get("material")
            if material is not None and (not isinstance(material, int) or material < 0 or material >= len(materials)):
                issues.append(f"mesh {mesh_index} primitive {primitive_index} references missing material")
    for index, texture in enumerate(textures):
        source = texture.get("source")
        if source is not None and (not isinstance(source, int) or source < 0 or source >= len(images)):
            issues.append(f"texture {index} references missing image")
    children = [child for node in document.get("nodes", []) for child in node.get("children", [])]
    if any(not isinstance(child, int) or child < 0 or child >= len(document.get("nodes", [])) for child in children):
        issues.append("node hierarchy references missing node")
    return {"valid": not issues, "issues": issues, "counts": {"accessors": len(accessors), "bufferViews": len(views), "buffers": len(buffers), "materials": len(materials), "textures": len(textures), "images": len(images)}}


def _glb_report(payload: bytes) -> dict:
    document = _glb_document(payload)
    contract = validate_gltf_contract(document)
    primitives = [primitive for mesh in document.get("meshes", []) for primitive in mesh.get("primitives", [])]
    accessors = document.get("accessors", [])
    def count(attribute: str) -> int:
        result = 0
        for primitive in primitives:
            index = primitive.get("attributes", {}).get(attribute)
            if isinstance(index, int) and index < len(accessors): result += int(accessors[index].get("count", 0))
        return result
    vertices = count("POSITION"); normals = count("NORMAL"); uvs = count("TEXCOORD_0")
    faces = sum(int(accessors[p["indices"]].get("count", 0)) // 3 for p in primitives if isinstance(p.get("indices"), int) and p["indices"] < len(accessors))
    materials = len(document.get("materials", [])); textures = len(document.get("textures", [])); images = len(document.get("images", []))
    score = 25 + (20 if primitives and vertices else 0) + (15 if normals else 0) + (12 if uvs else 0) + (10 if materials else 0) + (10 if textures and images else 0) + (8 if len(payload) > 1024 else 2)
    issues = list(contract["issues"])
    if not primitives or not vertices: issues.append("no renderable mesh primitives")
    if not normals: issues.append("missing vertex normals")
    if not uvs: issues.append("missing UV coordinates")
    if not materials: issues.append("missing material")
    if not textures or not images: issues.append("missing baked texture")
    if not contract["valid"]:
        score = min(score, 40)
    return {"format": "glb", "score": min(100, score), "metrics": {"vertices": vertices, "faces": faces, "primitives": len(primitives), "materials": materials, "textures": textures, "bytes": len(payload)}, "contract": contract, "issues": issues}


def assess_mesh(payload: bytes, asset_format: str, threshold: int = 75) -> dict:
    try:
        report = _obj_report(payload) if asset_format == "obj" else _glb_report(payload)
    except (ValueError, KeyError, IndexError, json.JSONDecodeError, struct.error) as error:
        report = {"format": asset_format, "score": 0, "metrics": {"bytes": len(payload)}, "issues": [str(error)]}
    report["threshold"] = threshold
    report["passed"] = report["score"] >= threshold
    report["actions"] = ["mesh-cleanup", "normal-repair", "uv-generation", "pbr-packaging"] if not report["passed"] else []
    return report
