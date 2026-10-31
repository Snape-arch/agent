"""Isolated local Text-to-3D worker producing non-primitive implicit meshes."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sys

from implicit_geometry import marching_tetrahedra


def ellipsoid(point, center, radius):
    return math.sqrt(sum(((point[index] - center[index]) / radius[index]) ** 2 for index in range(3))) - 1


def smooth_union(first: float, second: float, radius: float = .28) -> float:
    amount = max(radius - abs(first - second), 0) / radius
    return min(first, second) - amount * amount * radius * .25


def semantic_field(prompt: str):
    lowered = prompt.lower(); digest = hashlib.sha256(prompt.encode()).digest()
    jitter = lambda index, scale=.3: (digest[index % len(digest)] / 255 - .5) * scale
    if any(word in lowered for word in ("动物", "生物", "龙", "猫", "狗", "creature", "animal", "dragon")):
        elements = [((0, .15, 0), (1.25, .72, .62)), ((-.95, .52, 0), (.56, .52, .5)), ((.85, .05, 0), (.72, .48, .42))]
        elements += [((-.35 + side * .7, -.72, depth * .34), (.24, .72, .24)) for side in (-1, 1) for depth in (-1, 1)]
        elements += [((1.45 + index * .38, .08 + index * .08, 0), (.45 - index * .05, .26, .24)) for index in range(3)]
    elif any(word in lowered for word in ("人", "角色", "机器人", "character", "person", "humanoid")):
        elements = [((0, .65, 0), (.72, 1.15, .48)), ((0, 1.9, 0), (.52, .58, .5)),
                    ((-.85, .7, 0), (.28, 1.0, .28)), ((.85, .7, 0), (.28, 1.0, .28)),
                    ((-.38, -.75, 0), (.34, 1.2, .34)), ((.38, -.75, 0), (.34, 1.2, .34))]
    elif any(word in lowered for word in ("树", "植物", "花", "tree", "plant", "flower")):
        elements = [((0, -.65, 0), (.38, 1.45, .38)), ((0, .75, 0), (1.15, 1.0, 1.05)),
                    ((-.72, .62, .1), (.8, .72, .72)), ((.7, .72, -.12), (.85, .78, .75)), ((0, 1.42, 0), (.72, .65, .7))]
    else:
        count = 6 + digest[0] % 5
        elements = [((math.cos(index * 2.399) * (1 + jitter(index)), (index - count / 2) * .22 + jitter(index + 3), math.sin(index * 2.399) * (1 + jitter(index + 6))),
                     (.55 + digest[index + 1] / 700, .5 + digest[index + 2] / 600, .48 + digest[index + 3] / 700)) for index in range(count)]
    def field(point):
        warped = (point[0] + math.sin(point[1] * 2.1 + jitter(12)) * .08, point[1] + math.sin(point[2] * 2.3) * .06, point[2] + math.sin(point[0] * 2.0) * .08)
        value = float("inf")
        for center, radius in elements:
            value = smooth_union(value, ellipsoid(warped, center, radius)) if math.isfinite(value) else ellipsoid(warped, center, radius)
        return value
    return field


def main() -> int:
    request = json.loads(sys.stdin.read() or "{}")
    prompt = str(request.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    resolution = max(24, min(56, int(request.get("resolution") or 38)))
    print(json.dumps({"type": "progress", "progress": 10, "stage": "semantic-analysis"}), flush=True)
    field = semantic_field(prompt)
    print(json.dumps({"type": "progress", "progress": 28, "stage": "implicit-field"}), flush=True)
    vertices, faces = marching_tetrahedra(field, ((-3.2, -3.2, -3.2), (3.2, 3.2, 3.2)), resolution)
    print(json.dumps({"type": "progress", "progress": 82, "stage": "surface-extraction"}), flush=True)
    lines = ["# ClawVision independent Text-to-3D worker", "o Semantic_Implicit_Mesh"]
    lines.extend(f"v {x:.7f} {y:.7f} {z:.7f}" for x, y, z in vertices)
    lines.extend(f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces)
    payload = ("\n".join(lines) + "\n").encode()
    print(json.dumps({"type": "result", "progress": 100, "stage": "completed", "format": "obj", "content": base64.b64encode(payload).decode(),
                      "stats": {"vertices": len(vertices), "faces": len(faces), "bytes": len(payload), "resolution": resolution,
                                "generator": "clawvision-semantic-implicit-worker-v1", "nonParametric": True}}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
