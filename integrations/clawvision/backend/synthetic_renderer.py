"""Bounded CPU triangle rasterization with geometry-derived labels.

The diffuse/specular approximation is deliberately distinct from Three.js PBR.
No textures, animation, external resources or fabricated fallback geometry.
"""
from __future__ import annotations

import hashlib
import math
import struct
import time
import zlib

from errors import ValidationError

RENDERER = "clawvision.cpu-raster/1"
MAX_TRIANGLES = 20000
MAX_VERTICES = 60000
RESOLUTION = 512


def numpy():
    try:
        import numpy as np
    except ImportError as error:
        raise ValidationError("CPU synthesis requires numpy; install requirements-synthesis.txt") from error
    return np


def png(array):
    np = numpy()
    array = np.ascontiguousarray(array, dtype=np.uint8)
    height, width = array.shape[:2]
    color_type = 2 if array.ndim == 3 else 0
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    raw = b"".join(b"\0" + row.tobytes() for row in array)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _accessor(document, binary, index):
    np = numpy()
    try:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("invalid accessor index")
        entry = document["accessors"][index]
        if "sparse" in entry or entry.get("normalized"):
            raise ValueError("sparse or normalized geometry accessors are unsupported")
        view_index = entry["bufferView"]
        if isinstance(view_index, bool) or not isinstance(view_index, int) or view_index < 0:
            raise ValueError("invalid buffer view index")
        view = document["bufferViews"][view_index]
        if view.get("buffer", 0) != 0:
            raise ValueError("only embedded buffer 0 is supported")
        types = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
        sizes = {"SCALAR": 1, "VEC3": 3}
        dtype, size = np.dtype(types[entry["componentType"]]), sizes[entry["type"]]
        count = entry["count"]
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_VERTICES:
            raise ValueError("geometry accessor count exceeds 60000")
        offset = int(view.get("byteOffset", 0)) + int(entry.get("byteOffset", 0))
        stride = int(view.get("byteStride", dtype.itemsize * size))
        end = offset + (count - 1) * stride + size * dtype.itemsize
        view_end = int(view.get("byteOffset", 0)) + int(view["byteLength"])
        if offset < int(view.get("byteOffset", 0)) or stride < size * dtype.itemsize or end > min(len(binary), view_end):
            raise ValueError("geometry accessor exceeds embedded buffer bounds")
        values = np.ndarray((count, size), dtype=dtype, buffer=binary, offset=offset, strides=(stride, dtype.itemsize)).astype(np.float64)
        if not np.isfinite(values).all():
            raise ValueError("geometry contains non-finite values")
        return values[:, 0] if size == 1 else values
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        raise ValidationError(f"unsupported or invalid geometry accessor: {error}") from error


def _matrix(node):
    np = numpy()
    if "matrix" in node:
        matrix = np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4, order="F")
    else:
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        length = math.sqrt(x*x + y*y + z*z + w*w)
        if not math.isfinite(length) or length <= 0:
            raise ValidationError("invalid node quaternion")
        x, y, z, w = (v / length for v in (x, y, z, w))
        matrix = np.eye(4)
        matrix[:3, :3] = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                  [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                  [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]) @ np.diag(node.get("scale", [1, 1, 1]))
        matrix[:3, 3] = node.get("translation", [0, 0, 0])
    if not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]) or abs(np.linalg.det(matrix[:3, :3])) < 1e-12:
        raise ValidationError("node transform is non-finite, non-affine or singular")
    return matrix


def load_mesh(payload, format):
    np = numpy()
    from asset_scene import canonicalize_mesh_asset
    try:
        # Reject oversized text meshes before the canonicalizer allocates lists.
        if format == "obj":
            vertices_count, triangle_count = 0, 0
            for line in payload.splitlines():
                parts = line.split()
                if parts and parts[0] == b"v": vertices_count += 1
                elif parts and parts[0] == b"f": triangle_count += max(0, len(parts)-3)
                if vertices_count > MAX_VERTICES or triangle_count > MAX_TRIANGLES:
                    raise ValidationError("OBJ exceeds CPU synthesis geometry budget")
        elif format == "stl":
            if len(payload) >= 84 and 84+struct.unpack_from("<I", payload, 80)[0]*50 <= len(payload):
                if struct.unpack_from("<I", payload, 80)[0] > MAX_TRIANGLES:
                    raise ValidationError("STL exceeds CPU synthesis geometry budget")
            elif payload.lower().count(b"vertex") > MAX_TRIANGLES*3:
                raise ValidationError("STL exceeds CPU synthesis geometry budget")
        document, binary = canonicalize_mesh_asset(payload, format)
        if document.get("animations") or document.get("skins") or document.get("extensionsRequired"):
            raise ValidationError("CPU synthesis supports static uncompressed triangle meshes only")
        buffers = document.get("buffers", [])
        if len(buffers) != 1 or buffers[0].get("uri"):
            raise ValidationError("CPU synthesis requires one embedded geometry buffer")
        scene = document["scenes"][document.get("scene", 0)]
        positions, faces, normals = [], [], []
        visited, count, triangles = set(), 0, 0
        def walk(index, parent, ancestors):
            nonlocal count, triangles
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValidationError("invalid scene node index")
            if index in ancestors or len(ancestors) > 64 or len(visited) > 2000:
                raise ValidationError("scene hierarchy is cyclic or exceeds 2000 nodes / depth 64")
            visited.add(index)
            node = document["nodes"][index]
            if "skin" in node or node.get("weights"):
                raise ValidationError("skinning and morph weights are unsupported")
            transform = parent @ _matrix(node)
            if "mesh" in node:
                if isinstance(node["mesh"], bool) or not isinstance(node["mesh"], int) or node["mesh"] < 0:
                    raise ValidationError("invalid mesh index")
                mesh = document["meshes"][node["mesh"]]
                for primitive in mesh["primitives"]:
                    if primitive.get("mode", 4) != 4 or primitive.get("targets") or primitive.get("extensions"):
                        raise ValidationError("only uncompressed triangle primitives without morph targets are supported")
                    vertex = _accessor(document, binary, primitive["attributes"]["POSITION"])
                    if vertex.ndim != 2 or vertex.shape[1] != 3:
                        raise ValidationError("POSITION must contain VEC3 values")
                    index_values = _accessor(document, binary, primitive["indices"]) if "indices" in primitive else np.arange(len(vertex))
                    if index_values.ndim != 1 or len(index_values) % 3 or np.any(index_values < 0) or np.any(index_values >= len(vertex)) or np.any(index_values != np.floor(index_values)):
                        raise ValidationError("invalid triangle indices")
                    local_faces = index_values.astype(np.int64).reshape(-1, 3)
                    triangles += len(local_faces)
                    if count + len(vertex) > MAX_VERTICES or triangles > MAX_TRIANGLES:
                        raise ValidationError("CPU synthesis mesh exceeds 60000 vertices or 20000 triangles")
                    world = vertex @ transform[:3, :3].T + transform[:3, 3]
                    if "NORMAL" in primitive["attributes"]:
                        normal = _accessor(document, binary, primitive["attributes"]["NORMAL"])
                        if normal.shape != vertex.shape:
                            raise ValidationError("NORMAL accessor does not match POSITION")
                        normal = normal @ np.linalg.inv(transform[:3, :3])
                    else:
                        normal = np.zeros_like(world)
                        cross = np.cross(world[local_faces[:, 1]] - world[local_faces[:, 0]], world[local_faces[:, 2]] - world[local_faces[:, 0]])
                        for axis in range(3):
                            np.add.at(normal, local_faces[:, axis], cross)
                    lengths = np.linalg.norm(normal, axis=1)
                    normal /= np.maximum(lengths[:, None], 1e-12)
                    positions.append(world); normals.append(normal); faces.append(local_faces + count); count += len(vertex)
            for child in node.get("children", []):
                walk(child, transform, ancestors | {index})
        for index in scene.get("nodes", []):
            walk(index, np.eye(4), set())
        if not positions or not triangles:
            raise ValidationError("asset contains no renderable triangles")
        vertex, normal, face = np.concatenate(positions), np.concatenate(normals), np.concatenate(faces)
        if not np.isfinite(vertex).all():
            raise ValidationError("world geometry is non-finite")
        minimum, maximum = vertex.min(axis=0), vertex.max(axis=0)
        center, radius = (minimum + maximum) / 2, np.linalg.norm(maximum - minimum) / 2
        if not math.isfinite(radius) or radius <= 1e-10:
            raise ValidationError("asset has invalid spatial bounds")
        return (vertex - center) / radius, face, normal
    except (KeyError, IndexError, TypeError, ValueError, struct.error, OverflowError) as error:
        raise ValidationError(f"invalid static mesh: {error}") from error


def _direction(azimuth, elevation):
    np = numpy()
    a, e = math.radians(azimuth), math.radians(elevation)
    return np.array([math.sin(a)*math.cos(e), math.sin(e), math.cos(a)*math.cos(e)])


def _linear(color):
    np = numpy()
    value = np.array([int(color[i:i+2], 16) / 255 for i in (1, 3, 5)])
    return np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)


def bbox(mask):
    np = numpy()
    y, x = np.where(mask)
    return [int(x.min()), int(y.min()), int(x.max()-x.min()+1), int(y.max()-y.min()+1)] if len(x) else None


def rle(mask):
    np = numpy()
    values = mask.flatten(order="F").astype(np.uint8)
    boundaries = np.flatnonzero(values[1:] != values[:-1]) + 1
    counts = np.diff(np.concatenate(([0], boundaries, [len(values)]))).astype(int).tolist()
    if values[0]: counts.insert(0, 0)
    return {"size": list(mask.shape), "counts": counts}


def render(mesh, parameters, config, *, check=None, deadline=None):
    np = numpy()
    check = check or (lambda: None)
    def guard():
        check()
        if deadline is not None and time.monotonic() >= deadline:
            raise ValidationError("synthesis render time budget exceeded")
    guard()
    vertices, faces, normals = mesh
    camera_dir = _direction(parameters["cameraAzimuth"], parameters["cameraElevation"])
    camera = camera_dir * parameters["cameraDistance"]
    right = np.cross([0, 1, 0], camera_dir); right /= np.linalg.norm(right)
    up = np.cross(camera_dir, right)
    basis = np.stack((right, up, -camera_dir), axis=1)
    color = np.broadcast_to(_linear(config["background"]), (RESOLUTION, RESOLUTION, 3)).copy()
    depth = np.full((RESOLUTION, RESOLUTION), np.inf)
    ids = np.zeros((RESOLUTION, RESOLUTION), dtype=np.uint8)
    camera_vertices = (vertices - camera) @ basis
    focal = RESOLUTION / (2 * math.tan(math.radians(46 / 2)))
    projected = np.column_stack((RESOLUTION / 2 + focal * camera_vertices[:, 0] / camera_vertices[:, 2],
                                 RESOLUTION / 2 - focal * camera_vertices[:, 1] / camera_vertices[:, 2]))
    base = _linear(config["materialColor"])
    light = _direction(parameters["lightAzimuth"], parameters["lightElevation"])
    roughness, metalness = parameters["roughness"], parameters["metalness"]
    def raster(points, depths, object_id, ns=None):
        minimum = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        maximum = np.minimum(np.ceil(points.max(axis=0)).astype(int), RESOLUTION - 1)
        if np.any(minimum > maximum): return
        a, b, c = points
        denominator = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        if abs(denominator) < 1e-10: return
        for start in range(int(minimum[1]), int(maximum[1])+1, 64):
            guard()
            ys, xs = np.mgrid[start:min(start+64, int(maximum[1])+1), int(minimum[0]):int(maximum[0])+1]
            x, y = xs + .5, ys + .5
            w0 = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1])) / denominator
            w1 = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1])) / denominator
            w2 = 1-w0-w1
            reciprocal = w0/depths[0] + w1/depths[1] + w2/depths[2]
            z = np.divide(1, reciprocal, out=np.full_like(reciprocal, np.inf), where=reciprocal > 0)
            covered = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9) & (z < depth[ys, xs])
            if not covered.any(): continue
            if object_id == 1:
                weights = np.stack((w0/depths[0], w1/depths[1], w2/depths[2]), axis=-1) * z[..., None]
                normal = weights @ ns; normal /= np.maximum(np.linalg.norm(normal, axis=-1)[..., None], 1e-12)
                # Two-sided opaque geometry. Orient shading normals toward view.
                normal *= np.where((normal @ camera_dir) < 0, -1, 1)[..., None]
                diffuse = np.maximum(normal @ light, 0)
                halfway = light + camera_dir; halfway /= max(np.linalg.norm(halfway), 1e-12)
                specular = np.maximum(normal @ halfway, 0) ** (2 + 126 * (1-roughness))
                shaded = base * (1-metalness) * (.7 + parameters["lightIntensity"] * diffuse[..., None])
                shaded += ((1-metalness)*.04 + metalness*base) * parameters["lightIntensity"] * specular[..., None]
            else:
                shaded = _linear("#343434") * (.7 + parameters["lightIntensity"] * max(0, float(camera_dir @ light)))
            depth[ys[covered], xs[covered]] = z[covered]; ids[ys[covered], xs[covered]] = object_id
            color[ys[covered], xs[covered]] = shaded[covered] if object_id == 1 else shaded
    for index, face in enumerate(faces):
        if index % 32 == 0: guard()
        raster(projected[face], camera_vertices[face, 2], 1, normals[face])
    amodal = ids == 1
    if parameters["occluderSize"] > 0:
        size = parameters["occluderSize"]
        center = camera / 2 + right * .35
        corners = np.array([center + right*x*size/2 + up*y*size/2 for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        cv = (corners-camera) @ basis
        points = np.column_stack((RESOLUTION/2+focal*cv[:, 0]/cv[:, 2], RESOLUTION/2-focal*cv[:, 1]/cv[:, 2]))
        for face in ([0, 1, 2], [0, 2, 3]): raster(points[face], cv[face, 2], 2)
    visible = ids == 1
    clipped = bool(amodal[0].any() or amodal[-1].any() or amodal[:, 0].any() or amodal[:, -1].any())
    area, full_area = int(visible.sum()), int(amodal.sum())
    tone = np.clip((color*(2.51*color+.03))/(color*(2.43*color+.59)+.14), 0, 1)
    srgb = np.where(tone <= .0031308, tone*12.92, 1.055*np.power(tone, 1/2.4)-.055)
    rgb = np.rint(srgb*255).astype(np.uint8)
    result = {"image": png(rgb), "mask": png(visible.astype(np.uint8)*255), "amodalMask": png(amodal.astype(np.uint8)*255)}
    return result, {"visiblePixels": area, "amodalPixels": full_area, "visibleFraction": area/full_area if full_area else 0,
                    "bbox": bbox(visible), "amodalBbox": bbox(amodal), "clipped": clipped, "segmentation": rle(visible)}


def source_digest():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
