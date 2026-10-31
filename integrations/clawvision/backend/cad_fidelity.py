"""Geometric tolerance checks for CAD/mesh provider round trips."""

from __future__ import annotations

import math

from mesh_postprocess import parse_obj


def mesh_signature(payload: bytes) -> dict:
    vertices, faces = parse_obj(payload)
    if not vertices or not faces:
        raise ValueError("mesh contains no renderable geometry")
    minimum = [min(vertex[index] for vertex in vertices) for index in range(3)]
    maximum = [max(vertex[index] for vertex in vertices) for index in range(3)]
    extent = [maximum[index] - minimum[index] for index in range(3)]
    volume = 0.0
    area = 0.0
    for a, b, c in faces:
        va, vb, vc = vertices[a], vertices[b], vertices[c]
        cross = (
            (vb[1] - va[1]) * (vc[2] - va[2]) - (vb[2] - va[2]) * (vc[1] - va[1]),
            (vb[2] - va[2]) * (vc[0] - va[0]) - (vb[0] - va[0]) * (vc[2] - va[2]),
            (vb[0] - va[0]) * (vc[1] - va[1]) - (vb[1] - va[1]) * (vc[0] - va[0]),
        )
        area += math.sqrt(sum(value * value for value in cross)) / 2
        volume += (va[0] * (vb[1] * vc[2] - vb[2] * vc[1]) - va[1] * (vb[0] * vc[2] - vb[2] * vc[0]) + va[2] * (vb[0] * vc[1] - vb[1] * vc[0])) / 6
    return {"vertices": len(vertices), "faces": len(faces), "min": minimum, "max": maximum, "extent": extent, "surfaceArea": area, "volume": abs(volume)}


def compare_round_trip(source: bytes, result: bytes, *, linear_tolerance: float = 1e-4, relative_tolerance: float = .01) -> dict:
    before = mesh_signature(source)
    after = mesh_signature(result)
    extent_error = max(abs(left - right) for left, right in zip(before["extent"], after["extent"]))
    volume_denominator = max(before["volume"], 1e-12)
    area_denominator = max(before["surfaceArea"], 1e-12)
    volume_error = abs(before["volume"] - after["volume"]) / volume_denominator
    area_error = abs(before["surfaceArea"] - after["surfaceArea"]) / area_denominator
    face_ratio = after["faces"] / max(1, before["faces"])
    passed = extent_error <= linear_tolerance and volume_error <= relative_tolerance and area_error <= relative_tolerance and .25 <= face_ratio <= 4
    return {
        "passed": passed,
        "tolerances": {"linear": linear_tolerance, "relative": relative_tolerance, "faceRatio": [.25, 4]},
        "errors": {"extent": extent_error, "volumeRelative": volume_error, "surfaceAreaRelative": area_error, "faceRatio": face_ratio},
        "source": before,
        "result": after,
    }
