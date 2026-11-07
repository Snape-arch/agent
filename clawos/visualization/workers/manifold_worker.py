"""Manifold/trimesh command adapter for ClawVision geometry jobs."""
from __future__ import annotations
import base64, io, json, sys

def emit(kind, **values): print(json.dumps({"type": kind, **values}), flush=True)

def main():
    import trimesh
    request=json.load(sys.stdin);source=request["source"];operation=request.get("operation",{});raw=base64.b64decode(source["content"]);fmt=source["format"]
    emit("progress",progress=10,stage="loading")
    loaded=trimesh.load(io.BytesIO(raw),file_type=fmt,force="scene")
    mesh=trimesh.util.concatenate(tuple(loaded.geometry.values())) if isinstance(loaded,trimesh.Scene) else loaded
    mesh.remove_unreferenced_vertices(); mesh.merge_vertices()
    kind=str(operation.get("type") or operation.get("kind") or "repair")
    if kind in {"boolean","exact-boolean"} and operation.get("operand"):
        operand=operation["operand"];other=trimesh.load(io.BytesIO(base64.b64decode(operand["content"])),file_type=operand["format"],force="mesh")
        action=str(operation.get("action") or "union");mesh={"union":trimesh.boolean.union,"subtract":trimesh.boolean.difference,"intersect":trimesh.boolean.intersection}[action]([mesh,other],engine="manifold")
    target=int(operation.get("targetFaces") or 0)
    if target and len(mesh.faces)>target: mesh=mesh.simplify_quadric_decimation(face_count=target)
    emit("progress",progress=80,stage="exporting")
    output_format=str(request.get("outputFormat") or "glb").lower(); output=mesh.export(file_type=output_format)
    if isinstance(output,str):output=output.encode()
    emit("result",content=base64.b64encode(output).decode(),format=output_format,stats={"vertices":len(mesh.vertices),"faces":len(mesh.faces),"watertight":bool(mesh.is_watertight),"kernel":"manifold3d"})
if __name__=="__main__": main()
