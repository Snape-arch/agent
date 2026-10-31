"""Editable GLB/glTF scene documents with replayable non-destructive operations."""

from __future__ import annotations

import copy
import base64
import json
import math
import re
import struct
import uuid

from mesh_quality import assess_mesh

COMPONENTS = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
TYPE_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
COLORS = {"红": "#ef4444", "red": "#ef4444", "蓝": "#3b82f6", "blue": "#3b82f6", "绿": "#22c55e", "green": "#22c55e", "白": "#f8fafc", "white": "#f8fafc", "黑": "#18181b", "black": "#18181b", "金色": "#d4a72c", "gold": "#d4a72c", "银色": "#a8b4c4", "silver": "#a8b4c4"}


def _generated_uvs(positions: list[list[float]]) -> list[list[float]]:
    if not positions:return []
    mins=[min(row[axis] for row in positions) for axis in range(3)];maxs=[max(row[axis] for row in positions) for axis in range(3)];spans=[max(1e-9,maxs[axis]-mins[axis]) for axis in range(3)]
    drop=min(range(3),key=lambda axis:spans[axis]);axes=[axis for axis in range(3) if axis!=drop]
    return [[(row[axes[0]]-mins[axes[0]])/spans[axes[0]],(row[axes[1]]-mins[axes[1]])/spans[axes[1]]] for row in positions]


def _document_from_triangles(name: str, positions: list[list[float]], faces: list[list[int]], uvs: list[list[float]]|None=None) -> tuple[dict,bytes]:
    if not positions or not faces:raise ValueError("mesh contains no triangles")
    document={"asset":{"version":"2.0","generator":"ClawVision canonical mesh importer"},"scene":0,"scenes":[{"nodes":[0]}],"nodes":[{"mesh":0,"name":name}],"meshes":[{"name":name,"primitives":[]}],"materials":[{"name":"Imported PBR","pbrMetallicRoughness":{"baseColorFactor":[.72,.76,.82,1],"metallicFactor":.15,"roughnessFactor":.6}}],"buffers":[{"byteLength":0}],"bufferViews":[],"accessors":[]};binary=b""
    normals=_normals(positions,faces);uvs=uvs if uvs and len(uvs)==len(positions) else _generated_uvs(positions)
    position,binary=_append_accessor(document,binary,positions,5126,"VEC3",34962);normal,binary=_append_accessor(document,binary,normals,5126,"VEC3",34962);uv,binary=_append_accessor(document,binary,uvs,5126,"VEC2",34962)
    flat=[index for face in faces for index in face];component=5123 if len(positions)<65535 else 5125;indices,binary=_append_accessor(document,binary,flat,component,"SCALAR",34963)
    document["meshes"][0]["primitives"]=[{"attributes":{"POSITION":position,"NORMAL":normal,"TEXCOORD_0":uv},"indices":indices,"material":0}];document["buffers"][0]["byteLength"]=len(binary);return document,binary


def _document_from_points(name: str, positions: list[list[float]], colors: list[list[float]]|None=None) -> tuple[dict,bytes]:
    if not positions: raise ValueError("point cloud contains no vertices")
    document={"asset":{"version":"2.0","generator":"ClawVision PLY point-cloud importer"},"scene":0,"scenes":[{"nodes":[0]}],"nodes":[{"mesh":0,"name":name}],"meshes":[{"name":name,"primitives":[]}],"materials":[{"name":"Point cloud","pbrMetallicRoughness":{"baseColorFactor":[.49,.97,.78,1],"metallicFactor":0,"roughnessFactor":1}}],"buffers":[{"byteLength":0}],"bufferViews":[],"accessors":[]};binary=b""
    position,binary=_append_accessor(document,binary,positions,5126,"VEC3",34962);attributes={"POSITION":position}
    if colors and len(colors)==len(positions):
        color,binary=_append_accessor(document,binary,colors,5126,"VEC3",34962);attributes["COLOR_0"]=color
    document["meshes"][0]["primitives"]=[{"attributes":attributes,"mode":0,"material":0}];document["buffers"][0]["byteLength"]=len(binary);return document,binary


def canonicalize_mesh_asset(payload: bytes, asset_format: str, name: str="Imported mesh") -> tuple[dict,bytes]:
    """Convert OBJ/STL/ASCII PLY into the editable glTF scene representation."""
    asset_format=asset_format.lower()
    if asset_format in {"glb","gltf"}:return parse_asset(payload,asset_format)
    positions=[];faces=[]
    if asset_format=="obj":
        source=[]
        for raw in payload.decode("utf-8",errors="replace").splitlines():
            line=raw.strip()
            if line.startswith("v "):
                values=line.split();source.append([float(values[1]),float(values[2]),float(values[3])])
            elif line.startswith("f "):
                indices=[]
                for token in line.split()[1:]:
                    value=int(token.split("/",1)[0]);indices.append(value-1 if value>0 else len(source)+value)
                for offset in range(1,len(indices)-1):faces.append([indices[0],indices[offset],indices[offset+1]])
        positions=source
    elif asset_format=="stl":
        triangles=[]
        if len(payload)>=84 and 84+struct.unpack_from("<I",payload,80)[0]*50<=len(payload):
            count=struct.unpack_from("<I",payload,80)[0]
            for index in range(count):
                values=struct.unpack_from("<12fH",payload,84+index*50);triangles.append([list(values[3:6]),list(values[6:9]),list(values[9:12])])
        else:
            vertices=[]
            for match in re.finditer(rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",payload):
                vertices.append([float(match.group(axis)) for axis in (1,2,3)])
            triangles=[vertices[index:index+3] for index in range(0,len(vertices)-2,3)]
        lookup={}
        for triangle in triangles:
            face=[]
            for vertex in triangle:
                key=tuple(round(value,9) for value in vertex)
                if key not in lookup:lookup[key]=len(positions);positions.append(vertex)
                face.append(lookup[key])
            faces.append(face)
    elif asset_format=="ply":
        text=payload.decode("utf-8",errors="strict");lines=text.splitlines()
        if not lines or lines[0].strip()!="ply" or not any("format ascii" in line for line in lines[:20]): raise ValueError("binary PLY requires a configured professional geometry provider")
        end=next((index for index,line in enumerate(lines) if line.strip()=="end_header"),-1)
        if end<0: raise ValueError("invalid PLY header")
        vertex_count=next((int(line.split()[2]) for line in lines[:end] if line.startswith("element vertex ")),0);face_count=next((int(line.split()[2]) for line in lines[:end] if line.startswith("element face ")),0)
        properties=[line.split()[-1] for line in lines[:end] if line.startswith("property ") and "list" not in line];vertex_lines=lines[end+1:end+1+vertex_count];colors=[]
        for line in vertex_lines:
            values=line.split();row={name:values[index] for index,name in enumerate(properties) if index<len(values)};positions.append([float(row.get(axis,0)) for axis in ("x","y","z")])
            if all(channel in row for channel in ("red","green","blue")): colors.append([float(row[channel])/255 for channel in ("red","green","blue")])
        for line in lines[end+1+vertex_count:end+1+vertex_count+face_count]:
            values=[int(item) for item in line.split()];indices=values[1:1+values[0]]
            for offset in range(1,len(indices)-1): faces.append([indices[0],indices[offset],indices[offset+1]])
        if not faces:return _document_from_points(name,positions,colors)
    else:raise ValueError("editable scene import supports GLB, GLTF, OBJ, STL and ASCII PLY")
    return _document_from_triangles(name,positions,faces)


def parse_asset(payload: bytes, asset_format: str) -> tuple[dict, bytes]:
    if asset_format == "glb":
        if len(payload) < 20 or payload[:4] != b"glTF": raise ValueError("invalid GLB header")
        _, version, declared = struct.unpack_from("<4sII", payload)
        if version != 2 or declared != len(payload): raise ValueError("invalid GLB envelope")
        json_length, json_kind = struct.unpack_from("<I4s", payload, 12)
        if json_kind != b"JSON": raise ValueError("GLB JSON chunk missing")
        document=json.loads(payload[20:20+json_length].decode("utf-8").rstrip(" \0")); cursor=20+json_length; binary=b""
        if cursor+8 <= len(payload):
            binary_length,binary_kind=struct.unpack_from("<I4s",payload,cursor)
            if binary_kind==b"BIN\0": binary=payload[cursor+8:cursor+8+binary_length]
        return document,binary
    if asset_format == "gltf":
        document=json.loads(payload.decode("utf-8"));binary=b"";buffers=document.get("buffers",[])
        if buffers and isinstance(buffers[0].get("uri"),str) and buffers[0]["uri"].startswith("data:") and ";base64," in buffers[0]["uri"]:
            binary=base64.b64decode(buffers[0]["uri"].split(",",1)[1],validate=True)
        return document,binary
    raise ValueError("editable scene import currently supports GLB and GLTF")


def pack_glb(document: dict, binary: bytes) -> bytes:
    result=copy.deepcopy(document); result.setdefault("asset",{})["version"]="2.0"; result["asset"]["generator"]="ClawVision non-destructive scene editor"
    if binary:
        result.setdefault("buffers",[{"byteLength":len(binary)}]); result["buffers"][0].pop("uri",None); result["buffers"][0]["byteLength"]=len(binary)
    encoded=json.dumps(result,separators=(",",":"),ensure_ascii=False).encode(); encoded+=b" "*((4-len(encoded)%4)%4)
    binary+=b"\0"*((4-len(binary)%4)%4); total=12+8+len(encoded)+(8+len(binary) if binary else 0)
    payload=struct.pack("<4sII",b"glTF",2,total)+struct.pack("<I4s",len(encoded),b"JSON")+encoded
    if binary: payload+=struct.pack("<I4s",len(binary),b"BIN\0")+binary
    return payload


def _accessor(document: dict, binary: bytes, index: int) -> list:
    accessor=document.get("accessors",[])[index]; view=document.get("bufferViews",[])[accessor["bufferView"]]
    component=int(accessor["componentType"]); code,width=COMPONENTS[component]; size=TYPE_SIZE[accessor["type"]]
    start=int(view.get("byteOffset",0))+int(accessor.get("byteOffset",0)); stride=int(view.get("byteStride",width*size)); values=[]
    for item in range(int(accessor["count"])):
        row=struct.unpack_from("<"+code*size,binary,start+item*stride); values.append(list(row) if size>1 else row[0])
    return values


def _append_accessor(document: dict, binary: bytes, values: list, component: int, kind: str, target: int) -> tuple[int,bytes]:
    size=TYPE_SIZE[kind]; code,width=COMPONENTS[component]; offset=(len(binary)+3)//4*4; binary+=b"\0"*(offset-len(binary))
    packed=b"".join(struct.pack("<"+code*size,*value) if size>1 else struct.pack("<"+code,value) for value in values); binary+=packed
    view_index=len(document.setdefault("bufferViews",[])); document["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":len(packed),"target":target})
    entry={"bufferView":view_index,"componentType":component,"count":len(values),"type":kind}
    if values and kind=="VEC3": entry.update({"min":[min(row[i] for row in values) for i in range(3)],"max":[max(row[i] for row in values) for i in range(3)]})
    accessor_index=len(document.setdefault("accessors",[])); document["accessors"].append(entry); return accessor_index,binary


def _normalise(v):
    length=math.sqrt(sum(value*value for value in v)) or 1; return [value/length for value in v]


def _normals(positions: list[list[float]], faces: list[list[int]]) -> list[list[float]]:
    result=[[0.0,0.0,0.0] for _ in positions]
    for a,b,c in faces:
        va,vb,vc=positions[a],positions[b],positions[c]; u=[vb[i]-va[i] for i in range(3)]; v=[vc[i]-va[i] for i in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        for index in (a,b,c): result[index]=[result[index][axis]+n[axis] for axis in range(3)]
    return [_normalise(row) for row in result]


def _subdivide(positions,faces,uvs):
    lookup={}; next_positions=[list(row) for row in positions]; next_uvs=[list(row) for row in uvs] if uvs else []
    def midpoint(a,b):
        key=tuple(sorted((a,b)))
        if key not in lookup:
            lookup[key]=len(next_positions); next_positions.append([(positions[a][i]+positions[b][i])/2 for i in range(3)])
            if uvs: next_uvs.append([(uvs[a][i]+uvs[b][i])/2 for i in range(2)])
        return lookup[key]
    output=[]
    for a,b,c in faces:
        ab,bc,ca=midpoint(a,b),midpoint(b,c),midpoint(c,a); output.extend(([a,ab,ca],[ab,b,bc],[ca,bc,c],[ab,bc,ca]))
    return next_positions,output,next_uvs


def _repair_topology(positions,faces,uvs,fill_holes=True,remove_fragments=True):
    unique=set(); cleaned=[]
    for face in faces:
        if len(set(face))<3: continue
        key=tuple(sorted(face))
        if key not in unique: unique.add(key);cleaned.append(face)
    if remove_fragments and cleaned:
        vertex_faces={}
        for index,face in enumerate(cleaned):
            for vertex in face: vertex_faces.setdefault(vertex,set()).add(index)
        remaining=set(range(len(cleaned)));components=[]
        while remaining:
            seed=remaining.pop();component={seed};stack=[seed]
            while stack:
                for vertex in cleaned[stack.pop()]:
                    for neighbor in vertex_faces.get(vertex,set()):
                        if neighbor in remaining: remaining.remove(neighbor);component.add(neighbor);stack.append(neighbor)
            components.append(component)
        keep=max(components,key=len);cleaned=[face for index,face in enumerate(cleaned) if index in keep]
    edges={}
    for face in cleaned:
        for left,right in ((face[0],face[1]),(face[1],face[2]),(face[2],face[0])): edges[(min(left,right),max(left,right))]=edges.get((min(left,right),max(left,right)),0)+1
    boundary=[edge for edge,count in edges.items() if count==1];filled=0
    if fill_holes and boundary:
        adjacency={}
        for left,right in boundary: adjacency.setdefault(left,set()).add(right);adjacency.setdefault(right,set()).add(left)
        active=set(adjacency)
        while active:
            stack=[active.pop()];vertices=set(stack)
            while stack:
                for neighbor in adjacency[stack.pop()]:
                    if neighbor in active:active.remove(neighbor);vertices.add(neighbor);stack.append(neighbor)
            center=len(positions);positions.append([sum(positions[index][axis] for index in vertices)/len(vertices) for axis in range(3)])
            if uvs:uvs.append([sum(uvs[index][axis] for index in vertices if index<len(uvs))/max(1,sum(index<len(uvs) for index in vertices)) for axis in range(2)])
            component_edges=[edge for edge in boundary if edge[0] in vertices and edge[1] in vertices]
            for left,right in component_edges:cleaned.append([left,right,center]);filled+=1
    return positions,cleaned,uvs,{"removedFaces":len(faces)-len(cleaned)+filled,"filledBoundaryFaces":filled}


def _cluster_decimate(positions,faces,uvs,target):
    if len(faces)<=target:return positions,faces,uvs
    mins=[min(row[axis] for row in positions) for axis in range(3)];extent=max(max(row[axis] for row in positions)-mins[axis] for axis in range(3)) or 1;strength=max(2,(len(positions)*target/max(1,len(faces)))**(1/3))
    best=(positions,faces,uvs)
    for _ in range(10):
        cell=extent/max(1,strength);groups={};mapping=[]
        for row in positions:
            key=tuple(int((row[axis]-mins[axis])/cell) for axis in range(3));mapping.append(key);groups.setdefault(key,[]).append(row)
        keys={key:index for index,key in enumerate(groups)};next_positions=[[sum(row[axis] for row in rows)/len(rows) for axis in range(3)] for rows in groups.values()];next_uvs=[]
        if uvs:
            uv_groups={key:[] for key in groups}
            for index,key in enumerate(mapping):
                if index<len(uvs):uv_groups[key].append(uvs[index])
            next_uvs=[[sum(row[axis] for row in uv_groups[key])/max(1,len(uv_groups[key])) for axis in range(2)] for key in groups]
        seen=set();next_faces=[]
        for face in faces:
            mapped=[keys[mapping[index]] for index in face]
            if len(set(mapped))<3:continue
            identity=tuple(sorted(mapped))
            if identity not in seen:seen.add(identity);next_faces.append(mapped)
        if next_faces:best=(next_positions,next_faces,next_uvs)
        if len(next_faces)<=target:break
        strength*=.8
    return best


def _mesh_modifier(document: dict, binary: bytes, mesh_index: int, modifier: dict) -> tuple[int,bytes,dict]:
    source=copy.deepcopy(document.get("meshes",[])[mesh_index]); output_primitives=[]; stats={"modifier":modifier.get("kind"),"facesBefore":0,"facesAfter":0}
    for primitive in source.get("primitives",[]):
        attrs=primitive.get("attributes",{}); position_index=attrs.get("POSITION")
        if not isinstance(position_index,int) or primitive.get("mode",4)!=4: output_primitives.append(primitive); continue
        positions=_accessor(document,binary,position_index); indices=_accessor(document,binary,primitive["indices"]) if isinstance(primitive.get("indices"),int) else list(range(len(positions)))
        faces=[indices[i:i+3] for i in range(0,len(indices)-2,3)]; uvs=_accessor(document,binary,attrs["TEXCOORD_0"]) if isinstance(attrs.get("TEXCOORD_0"),int) else []
        stats["facesBefore"]+=len(faces); kind=modifier.get("kind")
        if kind=="subdivision" and len(faces)<100000: positions,faces,uvs=_subdivide(positions,faces,uvs)
        elif kind in {"decimate","remesh"}:
            target=max(12,min(200000,int(modifier.get("targetFaces") or max(12,len(faces)//2))))
            if target < len(faces): positions,faces,uvs=_cluster_decimate(positions,faces,uvs,target)
            elif kind=="remesh" and target>len(faces) and len(faces)<50000: positions,faces,uvs=_subdivide(positions,faces,uvs)
        repair_stats={}
        if kind in {"normal-repair","remesh"}: positions,faces,uvs,repair_stats=_repair_topology(positions,faces,uvs,bool(modifier.get("fillHoles",True)),bool(modifier.get("removeFragments",True)))
        if kind in {"bevel","chamfer"} and len(faces)<50000:positions,faces,uvs=_subdivide(positions,faces,uvs)
        normals=_normals(positions,faces)
        if kind in {"bevel","chamfer"}:
            amount=max(-.25,min(.25,float(modifier.get("amount") or .01))); positions=[[row[i]+normals[index][i]*amount for i in range(3)] for index,row in enumerate(positions)]
        pos_index,binary=_append_accessor(document,binary,positions,5126,"VEC3",34962); normal_index,binary=_append_accessor(document,binary,normals,5126,"VEC3",34962)
        flat=[index for face in faces for index in face]; component=5123 if len(positions)<65535 else 5125; index_index,binary=_append_accessor(document,binary,flat,component,"SCALAR",34963)
        next_attrs={"POSITION":pos_index,"NORMAL":normal_index}
        if not uvs:uvs=_generated_uvs(positions)
        if uvs:
            uv_index,binary=_append_accessor(document,binary,uvs,5126,"VEC2",34962); next_attrs["TEXCOORD_0"]=uv_index
        output={key:value for key,value in primitive.items() if key not in {"attributes","indices"}}; output.update({"attributes":next_attrs,"indices":index_index}); output_primitives.append(output); stats["facesAfter"]+=len(faces);stats.update(repair_stats)
    source["primitives"]=output_primitives; source["name"]=source.get("name",f"Mesh {mesh_index}")+" · "+str(modifier.get("kind")); new_index=len(document.setdefault("meshes",[])); document["meshes"].append(source); return new_index,binary,stats


def _rotate_quaternion(point,rotation):
    x,y,z=point;qx,qy,qz,qw=(list(rotation)+[0,0,0,1])[:4]
    tx=2*(qy*z-qz*y);ty=2*(qz*x-qx*z);tz=2*(qx*y-qy*x)
    return [x+qw*tx+(qy*tz-qz*ty),y+qw*ty+(qz*tx-qx*tz),z+qw*tz+(qx*ty-qy*tx)]


def _node_to_world(point,node):
    scale=(list(node.get("scale",[1,1,1]))+[1,1,1])[:3];rotated=_rotate_quaternion([point[axis]*scale[axis] for axis in range(3)],node.get("rotation",[0,0,0,1]));translation=(list(node.get("translation",[0,0,0]))+[0,0,0])[:3]
    return [rotated[axis]+translation[axis] for axis in range(3)]


def _world_to_node(point,node):
    translation=(list(node.get("translation",[0,0,0]))+[0,0,0])[:3];rotation=(list(node.get("rotation",[0,0,0,1]))+[0,0,0,1])[:4];inverse=[-rotation[0],-rotation[1],-rotation[2],rotation[3]];local=_rotate_quaternion([point[axis]-translation[axis] for axis in range(3)],inverse);scale=(list(node.get("scale",[1,1,1]))+[1,1,1])[:3]
    return [local[axis]/(scale[axis] if abs(scale[axis])>1e-9 else 1) for axis in range(3)]


def _mesh_geometry(document,binary,mesh_index,point_map=lambda point:point):
    positions=[];faces=[]
    for primitive in document.get("meshes",[])[mesh_index].get("primitives",[]):
        accessor=primitive.get("attributes",{}).get("POSITION")
        if not isinstance(accessor,int) or primitive.get("mode",4)!=4:continue
        source=[point_map(list(row)) for row in _accessor(document,binary,accessor)];indices=_accessor(document,binary,primitive["indices"]) if isinstance(primitive.get("indices"),int) else list(range(len(source)));offset=len(positions);positions.extend(source);faces.extend([[offset+int(indices[index+axis]) for axis in range(3)] for index in range(0,len(indices)-2,3)])
    return positions,faces


def _ray_x_intersections(positions,faces,y,z):
    hits=[]
    for a,b,c in faces:
        va,vb,vc=positions[a],positions[b],positions[c];denom=(vb[1]-vc[1])*(va[2]-vc[2])+(vc[2]-vb[2])*(va[1]-vc[1])
        if abs(denom)<1e-12:continue
        wa=((vb[1]-vc[1])*(z-vc[2])+(vc[2]-vb[2])*(y-vc[1]))/denom;wb=((vc[1]-va[1])*(z-vc[2])+(va[2]-vc[2])*(y-vc[1]))/denom;wc=1-wa-wb
        if wa>=-1e-7 and wb>=-1e-7 and wc>=-1e-7:hits.append(wa*va[0]+wb*vb[0]+wc*vc[0])
    hits.sort();unique=[]
    for value in hits:
        if not unique or abs(value-unique[-1])>1e-7:unique.append(value)
    return unique


def _voxel_occupancy(positions,faces,minimum,step,resolution):
    occupied=set()
    for iy in range(resolution):
        y=minimum[1]+(iy+.5)*step
        for iz in range(resolution):
            z=minimum[2]+(iz+.5)*step;hits=_ray_x_intersections(positions,faces,y,z)
            if not hits:continue
            for ix in range(resolution):
                x=minimum[0]+(ix+.5)*step
                if sum(value>x for value in hits)%2:occupied.add((ix,iy,iz))
    return occupied


def _surface_voxels(occupied,minimum,step):
    vertices=[];faces=[];lookup={}
    directions=[((-1,0,0),(0,4,6,2)),((1,0,0),(1,3,7,5)),((0,-1,0),(0,1,5,4)),((0,1,0),(2,6,7,3)),((0,0,-1),(0,2,3,1)),((0,0,1),(4,5,7,6))];corners=((0,0,0),(1,0,0),(0,1,0),(1,1,0),(0,0,1),(1,0,1),(0,1,1),(1,1,1))
    def vertex(key):
        if key not in lookup:lookup[key]=len(vertices);vertices.append([minimum[axis]+key[axis]*step for axis in range(3)])
        return lookup[key]
    for cell in occupied:
        for direction,quad in directions:
            neighbor=tuple(cell[axis]+direction[axis] for axis in range(3))
            if neighbor in occupied:continue
            ids=[vertex(tuple(cell[axis]+corners[index][axis] for axis in range(3))) for index in quad];faces.extend(([ids[0],ids[1],ids[2]],[ids[0],ids[2],ids[3]]))
    return vertices,faces


def _regularize_voxels(cells,resolution):
    """Close edge/corner-only voxel contacts that create non-manifold surfaces."""
    cells=set(cells);directions=((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    for _ in range(2):
        candidates=set()
        for cell in cells:
            for direction in directions:
                item=tuple(cell[axis]+direction[axis] for axis in range(3))
                if all(0<=item[axis]<resolution for axis in range(3)) and item not in cells:candidates.add(item)
        additions={item for item in candidates if sum(tuple(item[axis]+direction[axis] for axis in range(3)) in cells for direction in directions)>=2}
        if not additions:break
        cells.update(additions)
    return cells


def _boolean_mesh(document: dict, binary: bytes, base_mesh: int, cutter_mesh: int, operator: str, base_node: dict, cutter_node: dict, resolution: int=28) -> tuple[int,bytes,dict]:
    """Watertight deterministic voxel Boolean evaluated in the base node space."""
    base_positions,base_faces=_mesh_geometry(document,binary,base_mesh)
    cutter_map=lambda point:_world_to_node(_node_to_world(point,cutter_node),base_node);cutter_positions,cutter_faces=_mesh_geometry(document,binary,cutter_mesh,cutter_map)
    if not base_faces or not cutter_faces:raise ValueError("boolean targets require triangle meshes")
    all_positions=base_positions+cutter_positions;low=[min(row[axis] for row in all_positions) for axis in range(3)];high=[max(row[axis] for row in all_positions) for axis in range(3)];extent=max(high[axis]-low[axis] for axis in range(3)) or 1;resolution=max(12,min(48,int(resolution)));step=extent/(resolution-2);minimum=[low[axis]-step for axis in range(3)]
    base_cells=_voxel_occupancy(base_positions,base_faces,minimum,step,resolution);cutter_cells=_voxel_occupancy(cutter_positions,cutter_faces,minimum,step,resolution)
    cells=base_cells|cutter_cells if operator=="union" else base_cells-cutter_cells if operator=="subtract" else base_cells&cutter_cells;cells=_regularize_voxels(cells,resolution)
    if not cells:raise ValueError("boolean operation produced an empty mesh")
    positions,faces=_surface_voxels(cells,minimum,step);normals=_normals(positions,faces);uvs=_generated_uvs(positions)
    pos,binary=_append_accessor(document,binary,positions,5126,"VEC3",34962);normal,binary=_append_accessor(document,binary,normals,5126,"VEC3",34962);uv,binary=_append_accessor(document,binary,uvs,5126,"VEC2",34962);flat=[index for face in faces for index in face];component=5123 if len(positions)<65535 else 5125;indices,binary=_append_accessor(document,binary,flat,component,"SCALAR",34963)
    original=document.get("meshes",[])[base_mesh];material=next((primitive.get("material") for primitive in original.get("primitives",[]) if isinstance(primitive.get("material"),int)),None);primitive={"attributes":{"POSITION":pos,"NORMAL":normal,"TEXCOORD_0":uv},"indices":indices}
    if material is not None:primitive["material"]=material
    mesh={"name":original.get("name","Boolean")+f" · voxel-{operator}","primitives":[primitive]};new_index=len(document.setdefault("meshes",[]));document["meshes"].append(mesh)
    return new_index,binary,{"modifier":"boolean","kernel":"voxel-watertight","operator":operator,"resolution":resolution,"facesBefore":len(base_faces)+len(cutter_faces),"facesAfter":len(faces),"occupiedVoxels":len(cells)}


def scene_manifest(document: dict) -> dict:
    nodes=document.get("nodes",[]); parents={child:index for index,node in enumerate(nodes) for child in node.get("children",[])}; meshes=document.get("meshes",[]); accessors=document.get("accessors",[])
    result=[]
    for index,node in enumerate(nodes):
        mesh_index=node.get("mesh"); vertex_count=face_count=0; bounds=None; material_ids=[]
        if isinstance(mesh_index,int) and mesh_index<len(meshes):
            for primitive in meshes[mesh_index].get("primitives",[]):
                pos=primitive.get("attributes",{}).get("POSITION"); ind=primitive.get("indices")
                if isinstance(pos,int) and pos<len(accessors):
                    acc=accessors[pos]; vertex_count+=int(acc.get("count",0)); bounds={"min":acc.get("min",[0,0,0]),"max":acc.get("max",[0,0,0])}
                if isinstance(ind,int) and ind<len(accessors): face_count+=int(accessors[ind].get("count",0))//3
                if isinstance(primitive.get("material"),int): material_ids.append(primitive["material"])
        extras=node.get("extras",{}).get("clawvision",{}) if isinstance(node.get("extras"),dict) else {}
        result.append({"id":f"node_{index}","index":index,"name":str(node.get("name") or f"Node {index}"),"parentId":f"node_{parents[index]}" if index in parents else None,"children":[f"node_{item}" for item in node.get("children",[])],"meshIndex":mesh_index,"materialIds":material_ids,"translation":node.get("translation",[0,0,0]),"rotation":node.get("rotation",[0,0,0,1]),"scale":node.get("scale",[1,1,1]),"visible":not extras.get("hidden",False),"locked":bool(extras.get("locked",False)),"groupId":extras.get("groupId"),"vertexCount":vertex_count,"faceCount":face_count,"bounds":bounds,"modifiers":extras.get("modifiers",[])})
    materials=[]
    for index,material in enumerate(document.get("materials",[])):
        pbr=material.get("pbrMetallicRoughness",{}); materials.append({"id":index,"name":material.get("name",f"Material {index}"),"color":pbr.get("baseColorFactor",[1,1,1,1]),"metallic":pbr.get("metallicFactor",1),"roughness":pbr.get("roughnessFactor",1),"doubleSided":bool(material.get("doubleSided",False))})
    return {"nodes":result,"materials":materials,"nodeCount":len(result),"meshCount":len(meshes),"materialCount":len(materials)}


def _indices(targets) -> list[int]:
    result=[]
    for target in targets or []:
        match=re.fullmatch(r"node_(\d+)",str(target))
        if match: result.append(int(match.group(1)))
    return result


def apply_asset_operations(document: dict, binary: bytes, operations: list[dict]) -> tuple[dict,bytes,list[dict]]:
    result=copy.deepcopy(document); binary=bytes(binary); modifier_stats=[]
    for operation in operations:
        if operation.get("enabled",True) is False: continue
        kind=str(operation.get("type") or operation.get("kind") or ""); payload=operation.get("payload") if isinstance(operation.get("payload"),dict) else {}; targets=_indices(operation.get("targetIds"))
        if kind=="csg" or (kind=="modifier" and str(payload.get("kind"))=="boolean"):
            if len(targets)<2: raise ValueError("boolean operation requires base and cutter target nodes")
            base_index,cutter_index=targets[0],targets[1];nodes=result.get("nodes",[])
            if base_index>=len(nodes) or cutter_index>=len(nodes) or not isinstance(nodes[base_index].get("mesh"),int) or not isinstance(nodes[cutter_index].get("mesh"),int): raise ValueError("boolean targets must both contain meshes")
            operator=str(payload.get("operator") or payload.get("operation") or "subtract").lower()
            if operator not in {"union","subtract","intersect"}: raise ValueError("boolean operator must be union, subtract or intersect")
            next_mesh,binary,stats=_boolean_mesh(result,binary,nodes[base_index]["mesh"],nodes[cutter_index]["mesh"],operator,nodes[base_index],nodes[cutter_index],int(payload.get("resolution") or 28));nodes[base_index]["mesh"]=next_mesh
            nodes[base_index].setdefault("extras",{}).setdefault("clawvision",{}).setdefault("modifiers",[]).append({"id":str(operation.get("id") or "boolean"),"kind":"boolean","operator":operator,"cutterId":f"node_{cutter_index}"})
            cutter_extra=nodes[cutter_index].setdefault("extras",{}).setdefault("clawvision",{});cutter_extra.update({"hidden":True,"booleanCutter":True,"originalScale":nodes[cutter_index].get("scale",[1,1,1])});nodes[cutter_index]["scale"]=[0,0,0]
            modifier_stats.append({"nodeId":f"node_{base_index}",**stats});continue
        if kind=="duplicate":
            for index in targets:
                if index>=len(result.get("nodes",[])): continue
                clone=copy.deepcopy(result["nodes"][index]); clone["name"]=str(clone.get("name",f"Node {index}"))+" copy"; offset=payload.get("offset",[.25,0,0]); translation=clone.get("translation",[0,0,0]); clone["translation"]=[float(translation[i])+float(offset[i] if i<len(offset) else 0) for i in range(3)]; result["nodes"].append(clone); clone_index=len(result["nodes"])-1; attached=False
                for parent in result.get("nodes",[]):
                    if index in parent.get("children",[]): parent.setdefault("children",[]).append(clone_index); attached=True
                for scene in result.get("scenes",[]):
                    if index in scene.get("nodes",[]): scene.setdefault("nodes",[]).append(clone_index); attached=True
                if not attached: result.setdefault("scenes",[{"nodes":[]}])[0].setdefault("nodes",[]).append(clone_index)
            continue
        for index in targets:
            if index>=len(result.get("nodes",[])): continue
            node=result["nodes"][index]; node.setdefault("extras",{}).setdefault("clawvision",{})
            if kind=="transform":
                for field,default in (("translation",[0,0,0]),("rotation",[0,0,0,1]),("scale",[1,1,1])):
                    if field not in payload: continue
                    value=payload[field]; current=node.get(field,default)
                    node[field]=[float(current[i])+float(value[i]) for i in range(min(len(current),len(value)))] if payload.get("relative",False) else [float(item) for item in value]
            elif kind in {"visibility","lock","rename","group"}:
                if kind=="visibility":
                    visible=bool(payload.get("visible",True)); extras=node["extras"]["clawvision"]
                    if not visible and not extras.get("hidden"): extras["originalScale"]=node.get("scale",[1,1,1]); node["scale"]=[0,0,0]
                    elif visible and extras.get("hidden"): node["scale"]=extras.get("originalScale",[1,1,1])
                    extras["hidden"]=not visible
                elif kind=="lock": node["extras"]["clawvision"]["locked"]=bool(payload.get("locked",True))
                elif kind=="rename": node["name"]=str(payload.get("name") or node.get("name"))[:120]
                else: node["extras"]["clawvision"]["groupId"]=str(payload.get("groupId") or "group")
            elif kind=="delete":
                for parent in result.get("nodes",[]): parent["children"]=[child for child in parent.get("children",[]) if child!=index]
                for scene in result.get("scenes",[]): scene["nodes"]=[child for child in scene.get("nodes",[]) if child!=index]
                node["extras"]["clawvision"].update({"hidden":True,"deleted":True,"originalScale":node.get("scale",[1,1,1])}); node["scale"]=[0,0,0]
            elif kind=="material" and isinstance(node.get("mesh"),int):
                mesh=copy.deepcopy(result["meshes"][node["mesh"]]); next_primitives=[]
                for primitive in mesh.get("primitives",[]):
                    source_index=primitive.get("material"); material=copy.deepcopy(result.get("materials",[])[source_index]) if isinstance(source_index,int) and source_index<len(result.get("materials",[])) else {"pbrMetallicRoughness":{}}
                    pbr=material.setdefault("pbrMetallicRoughness",{}); color=payload.get("color")
                    if isinstance(color,str) and re.fullmatch(r"#[0-9a-fA-F]{6}",color): pbr["baseColorFactor"]=[int(color[i:i+2],16)/255 for i in (1,3,5)]+[1]
                    if "metallic" in payload: pbr["metallicFactor"]=max(0,min(1,float(payload["metallic"])))
                    if "roughness" in payload: pbr["roughnessFactor"]=max(0,min(1,float(payload["roughness"])))
                    repeat=payload.get("textureRepeat")
                    texture=pbr.get("baseColorTexture")
                    if isinstance(repeat,list) and len(repeat)>=2 and isinstance(texture,dict):
                        transform=texture.setdefault("extensions",{}).setdefault("KHR_texture_transform",{});transform["scale"]=[max(.01,float(repeat[0])),max(.01,float(repeat[1]))]
                        result.setdefault("extensionsUsed",[])
                        if "KHR_texture_transform" not in result["extensionsUsed"]: result["extensionsUsed"].append("KHR_texture_transform")
                    if "textureStrength" in payload: material.setdefault("extras",{}).setdefault("clawvision",{})["textureStrength"]=max(0,min(2,float(payload["textureStrength"])))
                    material["name"]=str(payload.get("name") or material.get("name") or "Edited material")+" · edit"; result.setdefault("materials",[]).append(material); primitive=copy.deepcopy(primitive); primitive["material"]=len(result["materials"])-1; next_primitives.append(primitive)
                mesh["primitives"]=next_primitives; result["meshes"].append(mesh); node["mesh"]=len(result["meshes"])-1
            elif kind=="modifier":
                modifier={"id":str(operation.get("id") or "mod_"+uuid.uuid4().hex[:8]),**payload}; modifier_kind=str(modifier.get("kind") or "")
                node["extras"]["clawvision"].setdefault("modifiers",[]).append(modifier)
                if modifier_kind=="mirror":
                    axis=max(0,min(2,int(modifier.get("axis",0)))); scale=list(node.get("scale",[1,1,1])); scale[axis]*=-1; node["scale"]=scale
                elif modifier_kind=="array":
                    count=max(1,min(20,int(modifier.get("count",2)))); offset=modifier.get("offset",[1,0,0]); base=list(node.get("translation",[0,0,0]))
                    for number in range(1,count):
                        clone=copy.deepcopy(node); clone["name"]=str(node.get("name",f"Node {index}"))+f" Array {number+1}"; clone["translation"]=[base[i]+float(offset[i])*number for i in range(3)]; result["nodes"].append(clone); clone_index=len(result["nodes"])-1; attached=False
                        for parent in result.get("nodes",[]):
                            if index in parent.get("children",[]): parent.setdefault("children",[]).append(clone_index); attached=True
                        for scene in result.get("scenes",[]):
                            if index in scene.get("nodes",[]): scene.setdefault("nodes",[]).append(clone_index); attached=True
                        if not attached: result.setdefault("scenes",[{"nodes":[]}])[0].setdefault("nodes",[]).append(clone_index)
                elif modifier_kind in {"subdivision","decimate","remesh","normal-repair","bevel","chamfer"} and isinstance(node.get("mesh"),int):
                    next_mesh,binary,stats=_mesh_modifier(result,binary,node["mesh"],modifier); node["mesh"]=next_mesh; modifier_stats.append({"nodeId":f"node_{index}",**stats})
    return result,binary,modifier_stats


def quality_report(payload: bytes, manifest: dict, threshold: int = 75) -> dict:
    report=assess_mesh(payload,"glb",threshold); issue_nodes=[]; topology={"degenerateFaces":0,"boundaryEdges":0,"nonManifoldEdges":0,"components":0}
    try:
        document,binary=parse_asset(payload,"glb")
        for node in manifest.get("nodes",[]):
            if not node.get("visible",True):continue
            mesh_index=node.get("meshIndex");node_issue=False
            if not isinstance(mesh_index,int) or mesh_index>=len(document.get("meshes",[])):continue
            for primitive in document["meshes"][mesh_index].get("primitives",[]):
                attrs=primitive.get("attributes",{});position_index=attrs.get("POSITION")
                if not isinstance(position_index,int):continue
                positions=_accessor(document,binary,position_index);indices=_accessor(document,binary,primitive["indices"]) if isinstance(primitive.get("indices"),int) else list(range(len(positions)));faces=[indices[i:i+3] for i in range(0,len(indices)-2,3)]
                edges={};vertex_faces={}
                for face_index,(a,b,c) in enumerate(faces):
                    va,vb,vc=positions[a],positions[b],positions[c];u=[vb[i]-va[i] for i in range(3)];v=[vc[i]-va[i] for i in range(3)];cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                    if math.sqrt(sum(value*value for value in cross))<1e-9:topology["degenerateFaces"]+=1;node_issue=True
                    for vertex in (a,b,c):vertex_faces.setdefault(vertex,set()).add(face_index)
                    for left,right in ((a,b),(b,c),(c,a)):edge=(min(left,right),max(left,right));edges[edge]=edges.get(edge,0)+1
                boundary=sum(count==1 for count in edges.values());non_manifold=sum(count>2 for count in edges.values());topology["boundaryEdges"]+=boundary;topology["nonManifoldEdges"]+=non_manifold;node_issue=node_issue or bool(non_manifold)
                remaining=set(range(len(faces)));components=0
                while remaining:
                    components+=1;stack=[remaining.pop()]
                    while stack:
                        for vertex in faces[stack.pop()]:
                            for neighbor in vertex_faces.get(vertex,set()):
                                if neighbor in remaining:remaining.remove(neighbor);stack.append(neighbor)
                topology["components"]+=components
            if node_issue:issue_nodes.append(node["id"])
    except (ValueError,KeyError,IndexError,struct.error):pass
    if topology["degenerateFaces"]:report["issues"].append(f"{topology['degenerateFaces']} degenerate faces")
    if topology["nonManifoldEdges"]:report["issues"].append(f"{topology['nonManifoldEdges']} non-manifold edges")
    if topology["components"]>max(1,manifest.get("meshCount",1))*4:report["issues"].append(f"{topology['components']} disconnected mesh components")
    penalty=min(25,topology["degenerateFaces"]+topology["nonManifoldEdges"]*2+max(0,topology["components"]-max(1,manifest.get("meshCount",1))*4));report["score"]=max(0,report["score"]-penalty);report["passed"]=report["score"]>=threshold
    report.setdefault("metrics",{}).update(topology);report["issueNodeIds"]=list(dict.fromkeys(issue_nodes));report["summary"]={"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}; return report


def _number(command: str, default: float = 1.0) -> float:
    matches=list(re.finditer(r"(-?\d+(?:\.\d+)?)\s*(mm|cm|m|%|度|°)?",command,re.I))
    if not matches: return default
    match=matches[-1]; value=float(match.group(1)); unit=(match.group(2) or "").lower()
    if unit=="mm": value/=1000
    elif unit=="cm": value/=100
    elif unit=="%": value/=100
    elif unit in {"度","°"}: value=math.radians(value)
    return value


def select_nodes(command: str, manifest: dict) -> list[str]:
    nodes=[node for node in manifest.get("nodes",[]) if node.get("meshIndex") is not None]; lower=command.lower(); direct=[node for node in nodes if str(node["name"]).lower() in lower]
    if direct: return [node["id"] for node in direct]
    positioned=[]
    for node in nodes:
        bounds=node.get("bounds") or {"min":[0,0,0],"max":[0,0,0]}; center=[(bounds["min"][i]+bounds["max"][i])/2+node.get("translation",[0,0,0])[i] for i in range(3)]; volume=math.prod(max(1e-9,bounds["max"][i]-bounds["min"][i]) for i in range(3)); positioned.append((node,center,volume))
    if any(word in lower for word in ("最大","largest","biggest")): positioned.sort(key=lambda item:item[2],reverse=True)
    elif any(word in lower for word in ("左侧","左边","left")): positioned.sort(key=lambda item:item[1][0])
    elif any(word in lower for word in ("右侧","右边","right")): positioned.sort(key=lambda item:item[1][0],reverse=True)
    elif any(word in lower for word in ("顶部","最高","top","upper")): positioned.sort(key=lambda item:item[1][1],reverse=True)
    count=2 if any(word in lower for word in ("两个","两侧","two ")) else 1
    return [item[0]["id"] for item in positioned[:count]]


def interpret_asset_command(command: str, manifest: dict) -> dict:
    command=command.strip()
    if not command or len(command)>1000: raise ValueError("asset command must contain 1 to 1000 characters")
    lower=command.lower(); targets=select_nodes(command,manifest)
    if not targets: raise ValueError("no editable mesh node found")
    clauses=[item.strip() for item in re.split(r"(?:并且|然后|同时|并|，|,|；|;)",command) if item.strip()]; operations=[]
    for clause in clauses:
        text=clause.lower(); value=_number(clause); kind=""; payload={}
        if any(word in text for word in ("隐藏","hide")): kind="visibility"; payload={"visible":False}
        elif any(word in text for word in ("显示","show")): kind="visibility"; payload={"visible":True}
        elif any(word in text for word in ("删除","delete","remove")): kind="delete"
        elif any(word in text for word in ("复制","duplicate","copy")): kind="duplicate"; payload={"offset":[value,0,0]}
        elif any(word in text for word in ("旋转","rotate")): kind="transform"; axis=0 if "x" in text else 2 if "z" in text else 1; rotation=[0,0,0,1]; rotation[axis]=math.sin(value/2); rotation[3]=math.cos(value/2); payload={"rotation":rotation}
        elif any(word in text for word in ("移动","move","抬高","降低")): kind="transform"; axis=0 if any(word in text for word in ("x","左","右")) else 2 if any(word in text for word in ("z","前","后")) else 1; sign=-1 if any(word in text for word in ("向左","降低","down","back","向后")) else 1; vector=[0,0,0]; vector[axis]=sign*value; payload={"translation":vector,"relative":True}
        elif any(word in text for word in ("缩放","放大","缩小","scale")): kind="transform"; factor=(1-value if any(word in text for word in ("缩小","smaller")) else 1+value if "%" in clause else value); payload={"scale":[factor]*3}
        elif any(word in text for word in ("减面","decimate")): kind="modifier"; payload={"kind":"decimate","targetFaces":max(12,int(value))}
        elif any(word in text for word in ("细分","subdivision")): kind="modifier"; payload={"kind":"subdivision"}
        elif any(word in text for word in ("重拓扑","remesh")): kind="modifier"; payload={"kind":"remesh","targetFaces":max(12,int(value))}
        elif any(word in text for word in ("倒角","bevel")): kind="modifier"; payload={"kind":"bevel","amount":max(.001,min(.25,value))}
        elif any(word in text for word in ("切角","chamfer")): kind="modifier"; payload={"kind":"chamfer","amount":max(.001,min(.25,value))}
        elif any(word in text for word in ("布尔","boolean")): kind="modifier"; payload={"kind":"boolean","operator":"intersect" if any(word in text for word in ("交","intersect")) else "union" if any(word in text for word in ("并","union")) else "subtract","resolution":28}
        elif any(word in text for word in ("法线","修复","repair")): kind="modifier"; payload={"kind":"normal-repair"}
        color=next((color_value for name,color_value in COLORS.items() if name in text),None)
        if not kind and (color or any(word in text for word in ("材质","颜色","metal","金属","roughness","粗糙"))): kind="material"
        if kind=="material":
            if color: payload["color"]=color
            if any(word in text for word in ("metal","金属")): payload.update({"metallic":.9,"roughness":.28})
        if kind: operations.append({"id":"op_"+uuid.uuid4().hex[:10],"type":kind,"targetIds":targets,"payload":payload,"enabled":True})
    if not operations: raise ValueError("command is not recognized; request transform, material, visibility, duplicate, delete or a mesh modifier")
    return {"command":command,"operations":operations,"affectedNodeIds":targets,"explanation":f"Planned {' + '.join(item['type'] for item in operations)} for {', '.join(targets)}"}
