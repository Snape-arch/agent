"""Small dependency-free SDF/CSG mesher using marching tetrahedra."""

from __future__ import annotations

import math
from typing import Callable

Vec3 = tuple[float, float, float]


def _rotate_inverse(point: Vec3, rotation: list[float]) -> Vec3:
    x, y, z = point; rx, ry, rz = (rotation + [0, 0, 0])[:3]
    x, y = x * math.cos(-rz) - y * math.sin(-rz), x * math.sin(-rz) + y * math.cos(-rz)
    x, z = x * math.cos(-ry) + z * math.sin(-ry), -x * math.sin(-ry) + z * math.cos(-ry)
    y, z = y * math.cos(-rx) - z * math.sin(-rx), y * math.sin(-rx) + z * math.cos(-rx)
    return x, y, z


def part_sdf(part: dict, point: Vec3) -> float:
    position = [float(value) for value in part.get("position", [0, 0, 0])]
    local = _rotate_inverse(tuple(point[index] - (position + [0, 0, 0])[index] for index in range(3)), [float(value) for value in part.get("rotation", [0, 0, 0])])
    x, y, z = local; size = [max(.001, float(value)) for value in part.get("size", [1, 1, 1])]
    sx, sy, sz = (size + [size[0], size[0]])[:3]; shape = part.get("shape", "box")
    if shape == "sphere":
        return math.sqrt((x / sx) ** 2 + (y / sy) ** 2 + (z / sz) ** 2) - 1
    if shape == "cylinder":
        radius = max(sx, sz); radial = math.sqrt(x * x + z * z) - radius; vertical = abs(y) - sy / 2
        return min(max(radial, vertical), 0) + math.sqrt(max(radial, 0) ** 2 + max(vertical, 0) ** 2)
    if shape == "torus":
        major, minor = sx, max(.01, sy); qx = math.sqrt(x * x + z * z) - major
        return math.sqrt(qx * qx + y * y) - minor
    if shape == "capsule":
        radius = sx; half = max(0, sy / 2 - radius); cy = max(-half, min(half, y))
        return math.sqrt(x * x + (y - cy) ** 2 + z * z) - radius
    bevel = max(0, float(part.get("bevel") or 0)); hx, hy, hz = sx / 2 - bevel, sy / 2 - bevel, sz / 2 - bevel
    qx, qy, qz = abs(x) - hx, abs(y) - hy, abs(z) - hz
    return min(max(qx, qy, qz), 0) + math.sqrt(max(qx, 0) ** 2 + max(qy, 0) ** 2 + max(qz, 0) ** 2) - bevel


def plan_field(plan: dict) -> Callable[[Vec3], float]:
    parts = [part for part in plan.get("parts", []) if isinstance(part, dict)]
    def field(point: Vec3) -> float:
        value = float("inf")
        for index, part in enumerate(parts):
            distance = part_sdf(part, point)
            operation = part.get("booleanOperation") or ("base" if index == 0 else "union")
            value = distance if index == 0 or operation == "base" else min(value, distance) if operation == "union" else max(value, -distance) if operation == "subtract" else max(value, distance)
        return value
    return field


def plan_bounds(plan: dict) -> tuple[Vec3, Vec3]:
    scale = float(plan.get("parameters", {}).get("scale", 1))
    mins = [float("inf")] * 3; maxs = [float("-inf")] * 3
    for part in plan.get("parts", []):
        position = [float(value) for value in part.get("position", [0, 0, 0])]
        size = [float(value) for value in part.get("size", [1, 1, 1])]
        radius = max(size) * 1.15
        for axis in range(3):
            mins[axis] = min(mins[axis], (position[axis] - radius) * scale)
            maxs[axis] = max(maxs[axis], (position[axis] + radius) * scale)
    if not all(math.isfinite(value) for value in mins + maxs):
        return (-2, -2, -2), (2, 2, 2)
    margin = max(maxs[axis] - mins[axis] for axis in range(3)) * .04 + .03
    return tuple(value - margin for value in mins), tuple(value + margin for value in maxs)


TETS = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))
CORNERS = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))


def marching_tetrahedra(field: Callable[[Vec3], float], bounds: tuple[Vec3, Vec3], resolution: int) -> tuple[list[Vec3], list[tuple[int, int, int]]]:
    minimum, maximum = bounds
    steps = tuple((maximum[axis] - minimum[axis]) / resolution for axis in range(3))
    vertices: list[Vec3] = []; faces: list[tuple[int, int, int]] = []; cache: dict[tuple[int, int, int], int] = {}
    def add(point: Vec3) -> int:
        key = tuple(round(value * 100_000) for value in point)
        if key not in cache:
            cache[key] = len(vertices); vertices.append(point)
        return cache[key]
    for ix in range(resolution):
        for iy in range(resolution):
            for iz in range(resolution):
                points = [(minimum[0] + (ix + dx) * steps[0], minimum[1] + (iy + dy) * steps[1], minimum[2] + (iz + dz) * steps[2]) for dx, dy, dz in CORNERS]
                values = [field(point) for point in points]
                if min(values) > 0 or max(values) < 0:
                    continue
                for tet in TETS:
                    intersections: list[Vec3] = []
                    for first, second in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
                        a, b = tet[first], tet[second]; va, vb = values[a], values[b]
                        if (va < 0) == (vb < 0):
                            continue
                        amount = va / (va - vb)
                        intersections.append(tuple(points[a][axis] + (points[b][axis] - points[a][axis]) * amount for axis in range(3)))
                    if len(intersections) == 3:
                        faces.append(tuple(add(point) for point in intersections))
                    elif len(intersections) == 4:
                        ids = [add(point) for point in intersections]; faces.extend(((ids[0], ids[1], ids[2]), (ids[0], ids[2], ids[3])))
    return vertices, faces


def mesh_plan_csg(plan: dict, resolution: int) -> tuple[list[Vec3], list[tuple[int, int, int]]]:
    scale = float(plan.get("parameters", {}).get("scale", 1))
    field = plan_field(plan)
    scaled_field = lambda point: field(tuple(value / scale for value in point))
    return marching_tetrahedra(scaled_field, plan_bounds(plan), resolution)
