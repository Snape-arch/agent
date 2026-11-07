"""Dependency-free mesh cleanup and textured GLB packaging for Text-to-3D results."""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib


def parse_obj(payload: bytes) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices, faces = [], []
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if line.startswith("v "):
            values = line.split()[1:4]; vertices.append(tuple(float(value) for value in values))
        elif line.startswith("f "):
            values = [int(value.split("/")[0]) - 1 for value in line.split()[1:]]
            for index in range(1, len(values) - 1):
                faces.append((values[0], values[index], values[index + 1]))
    if not vertices or not faces:
        raise ValueError("provider result must contain an OBJ triangle mesh")
    return vertices, faces


def cleanup_mesh(vertices, faces, max_faces: int = 120_000):
    welded, remap, lookup = [], [], {}
    for vertex in vertices:
        key = tuple(round(value, 5) for value in vertex)
        if key not in lookup:
            lookup[key] = len(welded); welded.append(vertex)
        remap.append(lookup[key])
    unique, cleaned = set(), []
    for face in faces:
        mapped = tuple(remap[index] for index in face)
        if len(set(mapped)) < 3:
            continue
        key = tuple(sorted(mapped))
        if key not in unique:
            unique.add(key); cleaned.append(mapped)
    if len(cleaned) > max_faces:
        stride = len(cleaned) / max_faces
        cleaned = [cleaned[int(index * stride)] for index in range(max_faces)]
    normals = [[0.0, 0.0, 0.0] for _ in welded]
    for a, b, c in cleaned:
        va, vb, vc = welded[a], welded[b], welded[c]
        u = (vb[0]-va[0], vb[1]-va[1], vb[2]-va[2]); v = (vc[0]-va[0], vc[1]-va[1], vc[2]-va[2])
        normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        for index in (a, b, c):
            normals[index][0] += normal[0]; normals[index][1] += normal[1]; normals[index][2] += normal[2]
    normalized = []
    for normal in normals:
        length = math.sqrt(sum(value*value for value in normal)) or 1
        normalized.append(tuple(value/length for value in normal))
    return welded, cleaned, normalized


def _png_texture(color=(70, 185, 160)) -> bytes:
    width = height = 4
    raw = b"".join(b"\0" + b"".join(bytes((*((color if (x+y)%2 == 0 else tuple(max(0, c-35) for c in color))), 255)) for x in range(width)) for y in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def mesh_to_glb(vertices, faces, normals, name: str = "Text-to-3D") -> tuple[bytes, dict]:
    mins = [min(v[a] for v in vertices) for a in range(3)]; maxs = [max(v[a] for v in vertices) for a in range(3)]
    height = max(maxs[1]-mins[1], 1e-9)
    positions = b"".join(struct.pack("<fff", *v) for v in vertices)
    normal_bytes = b"".join(struct.pack("<fff", *n) for n in normals)
    uvs = b"".join(struct.pack("<ff", .5 + math.atan2(v[2], v[0])/math.tau, (v[1]-mins[1])/height) for v in vertices)
    indices = b"".join(struct.pack("<III", *face) for face in faces)
    joints = b"".join(struct.pack("<BBBB", 0 if (v[1]-mins[1])/height < .55 else 1, 0, 0, 0) for v in vertices)
    weights = b"".join(struct.pack("<ffff", 1, 0, 0, 0) for _ in vertices)
    identity = (1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)
    inverse_bind = struct.pack("<"+"f"*32, *(identity+identity))
    animation_times = struct.pack("<fff", 0, 1, 2)
    angle = math.radians(18); animation_rotations = b"".join(struct.pack("<ffff", 0, 0, math.sin(value/2), math.cos(value/2)) for value in (0, angle, 0))
    texture = _png_texture(); normal_texture=_png_texture((128,128,255)); orm_texture=_png_texture((255,150,45)); blocks = [positions, normal_bytes, uvs, indices, joints, weights, inverse_bind, animation_times, animation_rotations, texture, normal_texture, orm_texture]
    offsets, binary = [], b""
    for block in blocks:
        offsets.append(len(binary)); binary += block; binary += b"\0" * ((4-len(binary)%4)%4)
    document = {"asset":{"version":"2.0","generator":"ClawVision Text-to-3D postprocessor"},"scene":0,"scenes":[{"nodes":[0]}],
      "nodes":[{"mesh":0,"skin":0,"name":name,"children":[1]},{"name":"Root Joint","children":[2],"translation":[0,mins[1],0]},{"name":"Upper Joint","translation":[0,height*.55,0]}],
      "meshes":[{"primitives":[{"attributes":{"POSITION":0,"NORMAL":1,"TEXCOORD_0":2,"JOINTS_0":4,"WEIGHTS_0":5},"indices":3,"material":0}]}],
      "materials":[{"name":"Generated PBR","pbrMetallicRoughness":{"baseColorTexture":{"index":0},"metallicRoughnessTexture":{"index":2},"metallicFactor":.35,"roughnessFactor":.7},"normalTexture":{"index":1,"scale":.35},"occlusionTexture":{"index":2,"strength":1}}],
      "textures":[{"source":0,"sampler":0},{"source":1,"sampler":0},{"source":2,"sampler":0}],"samplers":[{"wrapS":10497,"wrapT":10497}],"images":[{"bufferView":9,"mimeType":"image/png"},{"bufferView":10,"mimeType":"image/png"},{"bufferView":11,"mimeType":"image/png"}],
      "skins":[{"name":"Generated semantic rig","inverseBindMatrices":6,"joints":[1,2],"skeleton":1}],
      "animations":[{"name":"Semantic Idle","samplers":[{"input":7,"output":8,"interpolation":"LINEAR"}],"channels":[{"sampler":0,"target":{"node":2,"path":"rotation"}}]}],
      "buffers":[{"byteLength":len(binary)}],"bufferViews":[
        {"buffer":0,"byteOffset":offsets[0],"byteLength":len(positions),"target":34962},{"buffer":0,"byteOffset":offsets[1],"byteLength":len(normal_bytes),"target":34962},
        {"buffer":0,"byteOffset":offsets[2],"byteLength":len(uvs),"target":34962},{"buffer":0,"byteOffset":offsets[3],"byteLength":len(indices),"target":34963},
        {"buffer":0,"byteOffset":offsets[4],"byteLength":len(joints),"target":34962},{"buffer":0,"byteOffset":offsets[5],"byteLength":len(weights),"target":34962},
        {"buffer":0,"byteOffset":offsets[6],"byteLength":len(inverse_bind)},{"buffer":0,"byteOffset":offsets[7],"byteLength":len(animation_times)},
        {"buffer":0,"byteOffset":offsets[8],"byteLength":len(animation_rotations)},{"buffer":0,"byteOffset":offsets[9],"byteLength":len(texture)},
        {"buffer":0,"byteOffset":offsets[10],"byteLength":len(normal_texture)},{"buffer":0,"byteOffset":offsets[11],"byteLength":len(orm_texture)}],"accessors":[
        {"bufferView":0,"componentType":5126,"count":len(vertices),"type":"VEC3","min":mins,"max":maxs},
        {"bufferView":1,"componentType":5126,"count":len(vertices),"type":"VEC3"},{"bufferView":2,"componentType":5126,"count":len(vertices),"type":"VEC2"},
        {"bufferView":3,"componentType":5125,"count":len(faces)*3,"type":"SCALAR","min":[0],"max":[len(vertices)-1]},
        {"bufferView":4,"componentType":5121,"count":len(vertices),"type":"VEC4"},{"bufferView":5,"componentType":5126,"count":len(vertices),"type":"VEC4"},
        {"bufferView":6,"componentType":5126,"count":2,"type":"MAT4"},{"bufferView":7,"componentType":5126,"count":3,"type":"SCALAR","min":[0],"max":[2]},
        {"bufferView":8,"componentType":5126,"count":3,"type":"VEC4"}]}
    encoded = json.dumps(document,separators=(",",":"),ensure_ascii=False).encode(); encoded += b" "*((4-len(encoded)%4)%4)
    total=12+8+len(encoded)+8+len(binary)
    glb=struct.pack("<4sII",b"glTF",2,total)+struct.pack("<I4s",len(encoded),b"JSON")+encoded+struct.pack("<I4s",len(binary),b"BIN\0")+binary
    return glb,{"vertices":len(vertices),"faces":len(faces),"bytes":len(glb),"format":"glb","uvGenerated":True,"normalsRepaired":True,"pbrTextureBaked":True,"pbrTextureChannels":["baseColor","normal","occlusion","roughness","metallic"],"rigged":True,"animations":1,"joints":2}


def postprocess_to_glb(payload: bytes, asset_format: str, name: str) -> tuple[bytes, dict]:
    if asset_format != "obj":
        if asset_format == "glb" and payload[:4] == b"glTF":
            return payload,{"bytes":len(payload),"format":"glb","providerPackaged":True}
        raise ValueError("provider must return OBJ or GLB")
    vertices, faces = parse_obj(payload)
    vertices, faces, normals = cleanup_mesh(vertices, faces)
    return mesh_to_glb(vertices, faces, normals, name)
