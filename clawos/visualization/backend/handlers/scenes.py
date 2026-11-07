"""Scenes adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import base64
import json
import os
import re
import uuid


class ScenesHandler:
    runtime: HandlerRuntime

    def _scene_row(self,scene_id: str):
        with self.runtime.DB_LOCK,self.runtime.connect() as db: row=db.execute("SELECT * FROM model_scenes WHERE id=? AND tenant_id=?",(scene_id,self.principal.tenant_id)).fetchone()
        if not row: raise ValueError("model scene not found")
        return row


    def _render_model_scene(self,row,operations: list[dict]) -> dict:
        with self.runtime.DB_LOCK,self.runtime.connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(row["source_asset_id"],)).fetchone()
        if not asset: raise ValueError("source model asset not found")
        stored=self.runtime.OBJECT_STORE.get_json(asset["object_key"]); payload=base64.b64decode(stored["base64"],validate=True); document,binary=self.runtime.parse_asset(payload,asset["format"])
        if asset["format"]=="gltf" and not binary:
            uri=(document.get("buffers") or [{}])[0].get("uri")
            resource=next((item for item in stored.get("resources",[]) if item.get("name")==uri),None)
            if resource and resource.get("base64"): binary=base64.b64decode(resource["base64"],validate=True)
            if not binary and any(str(operation.get("type")) in {"modifier","csg","remesh","repair"} for operation in operations): raise ValueError("glTF mesh modifiers require an embedded buffer or an uploaded .bin resource")
        document,binary,modifier_stats=self.runtime.apply_asset_operations(document,binary,operations); manifest=self.runtime.scene_manifest(document)
        if asset["format"]=="glb":
            output=self.runtime.pack_glb(document,binary); quality=self.runtime.quality_report(output,manifest,max(50,min(100,int(os.environ.get("MODEL_SCENE_QUALITY_THRESHOLD","70")))))
        else:
            if binary:
                document.setdefault("buffers",[{"byteLength":len(binary)}]);document["buffers"][0]["byteLength"]=len(binary);document["buffers"][0]["uri"]="data:application/octet-stream;base64,"+base64.b64encode(binary).decode("ascii")
            output=json.dumps(document,separators=(",",":"),ensure_ascii=False).encode(); score=85 if manifest["meshCount"] else 20; quality={"format":"gltf","score":score,"threshold":70,"passed":score>=70,"issues":[] if score>=70 else ["no renderable meshes"],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
        return {"format":asset["format"],"name":asset["name"],"payload":output,"resources":stored.get("resources",[]),"manifest":manifest,"quality":quality,"modifierStats":modifier_stats}


    def _persist_model_scene_version(self,row,operations: list[dict],command: str,cancel_check=None) -> dict:
        rendered=self._render_model_scene(row,operations)
        if cancel_check and cancel_check():raise RuntimeError("model operation cancelled")
        version=int(row["version"])+1
        metadata={"source":"model-scene-release","sceneId":row["id"],"sourceAssetId":row["source_asset_id"],"operationCount":len(operations),"command":command[:500],"quality":rendered["quality"],"modifierStats":rendered["modifierStats"]}
        asset=self.runtime.store_model_asset(rendered["name"],rendered["format"],rendered["payload"],metadata,rendered["resources"],self.principal.tenant_id); created=self.runtime.now_iso(); version_id="msv_"+uuid.uuid4().hex[:12]
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            db.execute("UPDATE model_scenes SET current_asset_id=?,version=?,operations=?,scene_json=?,quality=?,updated_at=? WHERE id=?",(asset["id"],version,json.dumps(operations,ensure_ascii=False),json.dumps(rendered["manifest"],ensure_ascii=False),json.dumps(rendered["quality"],ensure_ascii=False),created,row["id"]))
            db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",(version_id,row["id"],version,asset["id"],json.dumps(operations,ensure_ascii=False),json.dumps(rendered["manifest"],ensure_ascii=False),json.dumps(rendered["quality"],ensure_ascii=False),created))
            updated=db.execute("SELECT * FROM model_scenes WHERE id=?",(row["id"],)).fetchone()
        return {**self.runtime.serialize_model_scene(updated,True),"asset":asset,"modifierStats":rendered["modifierStats"]}


    def _scene_agent_payload(self,run_id: str) -> dict | None:
        item=self.runtime.serialize_scene_agent_run(run_id)
        if item and isinstance(item.get("preview"),dict) and item["preview"].get("objectKey"):
            try:item["preview"]={**item["preview"],"asset":self.runtime.OBJECT_STORE.get_json(item["preview"]["objectKey"])}
            except (FileNotFoundError,KeyError):item["preview"]={**item["preview"],"unavailable":True}
        return item


    def _import_model_scene(self,asset_id: str,body: dict) -> None:
        with self.runtime.DB_LOCK,self.runtime.connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(asset_id,)).fetchone()
        if not asset: return self._json({"error":"model asset not found"},HTTPStatus.NOT_FOUND)
        stored=self.runtime.OBJECT_STORE.get_json(asset["object_key"]); payload=base64.b64decode(stored["base64"],validate=True)
        if asset["format"] in {"obj","stl","ply"}:
            document,binary=self.runtime.canonicalize_mesh_asset(payload,asset["format"],asset["name"]);canonical_payload=self.runtime.pack_glb(document,binary);stem=re.sub(r"\.(obj|stl|ply)$","",asset["name"],flags=re.I)
            canonical=self.runtime.store_model_asset(f"{stem}.glb","glb",canonical_payload,{"source":"canonical-editable-import","originalAssetId":asset_id,"originalFormat":asset["format"],"assetStage":"raw-canonical"},tenant_id=self.principal.tenant_id);asset_id=canonical["id"]
            with self.runtime.DB_LOCK,self.runtime.connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(asset_id,)).fetchone()
            stored=self.runtime.OBJECT_STORE.get_json(asset["object_key"]);payload=canonical_payload
        elif asset["format"] in {"step","iges","brep"}:raise ValueError("STEP/IGES/B-Rep must be tessellated by a configured OpenCascade or external geometry provider before scene import")
        else:document,_=self.runtime.parse_asset(payload,asset["format"])
        manifest=self.runtime.scene_manifest(document)
        quality=self.runtime.quality_report(payload,manifest,70) if asset["format"]=="glb" else {"format":"gltf","score":85 if manifest["meshCount"] else 20,"threshold":70,"passed":bool(manifest["meshCount"]),"issues":[],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
        scene_id="modelscene_"+uuid.uuid4().hex[:12]; name=str(body.get("name") or asset["name"]); created=self.runtime.now_iso(); operations=[]; version_id="msv_"+uuid.uuid4().hex[:12]
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            db.execute("INSERT INTO model_scenes(id,name,source_asset_id,current_asset_id,version,operations,scene_json,quality,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(scene_id,name,asset_id,asset_id,1,"[]",json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created,created,self.principal.tenant_id))
            db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",(version_id,scene_id,1,asset_id,"[]",json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created))
            row=db.execute("SELECT * FROM model_scenes WHERE id=?",(scene_id,)).fetchone()
        self._json({"data":self.runtime.serialize_model_scene(row,True)},HTTPStatus.CREATED)


    def _model_scene_command(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); manifest=self.runtime.json_value(row["scene_json"],{}); result=self.runtime.interpret_asset_command(str(body.get("command") or ""),manifest); self._json({"data":result},HTTPStatus.CREATED)


    def _preview_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); additions=body.get("operations") if isinstance(body.get("operations"),list) else []; operations=self.runtime.json_value(row["operations"],[])+additions
        rendered=self._render_model_scene(row,operations); self._json({"data":{"sceneId":scene_id,"operations":operations,"scene":rendered["manifest"],"quality":rendered["quality"],"modifierStats":rendered["modifierStats"],"asset":{"name":rendered["name"],"format":rendered["format"],"base64":base64.b64encode(rendered["payload"]).decode("ascii"),"resources":rendered["resources"]}}})


    def _apply_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); additions=body.get("operations") if isinstance(body.get("operations"),list) else []
        limit=500 if body.get("replace") else 50
        if (not additions and not body.get("replace")) or len(additions)>limit: raise ValueError(f"operations must contain {'0' if body.get('replace') else '1'} to {limit} items")
        existing=[] if body.get("replace") else self.runtime.json_value(row["operations"],[])
        if len(existing)+len(additions)>500: raise ValueError("scene operation stack exceeds 500 items")
        locked={node["id"] for node in self.runtime.json_value(row["scene_json"],{}).get("nodes",[]) if node.get("locked")}
        if any(locked.intersection(operation.get("targetIds",[])) and operation.get("type")!="lock" for operation in additions): raise ValueError("one or more target nodes are locked")
        result=self._persist_model_scene_version(row,existing+additions,str(body.get("command") or "manual edit")); self._json({"data":result},HTTPStatus.CREATED)


    def _restore_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); requested=int(body.get("version") or 0)
        with self.runtime.DB_LOCK,self.runtime.connect() as db: version=db.execute("SELECT operations FROM model_scene_versions WHERE scene_id=? AND version=?",(scene_id,requested)).fetchone()
        if not version: return self._json({"error":"model scene version not found"},HTTPStatus.NOT_FOUND)
        result=self._persist_model_scene_version(row,self.runtime.json_value(version["operations"],[]),f"restore version {requested}"); self._json({"data":result},HTTPStatus.CREATED)


    def _repair_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); manifest=self.runtime.json_value(row["scene_json"],{}); targets=[node["id"] for node in manifest.get("nodes",[]) if node.get("meshIndex") is not None]
        operations=[{"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"normal-repair"},"enabled":True}]
        if body.get("decimate"):
            operations.append({"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"decimate","targetFaces":max(100,int(body.get("targetFaces") or 50000))},"enabled":True})
        base_operations=self.runtime.json_value(row["operations"],[])+operations; result=self._persist_model_scene_version(row,base_operations,"automatic mesh repair"); total_faces=sum(int(node.get("faceCount") or 0) for node in manifest.get("nodes",[]));lod_assets=[]
        for level,ratio in ((1,.5),(2,.25)):
            target=max(100,int(total_faces*ratio));lod_operation={"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"decimate","targetFaces":target},"enabled":True};rendered=self._render_model_scene(row,base_operations+[lod_operation]);stem=re.sub(r"\.(glb|gltf)$","",rendered["name"],flags=re.I);lod_assets.append(self.runtime.store_model_asset(f"{stem}.lod{level}.{rendered['format']}",rendered["format"],rendered["payload"],{"source":"model-scene-lod","sceneId":scene_id,"lod":level,"targetFaces":target,"quality":rendered["quality"]},rendered["resources"],self.principal.tenant_id))
        result["lodAssets"]=lod_assets;self._json({"data":result},HTTPStatus.CREATED)


    def _export_model_scene(self,scene_id: str) -> None:
        row=self._scene_row(scene_id)
        with self.runtime.DB_LOCK,self.runtime.connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(row["current_asset_id"],)).fetchone()
        stored=self.runtime.OBJECT_STORE.get_json(asset["object_key"]); self._json({"data":{"id":asset["id"],"name":asset["name"],"format":asset["format"],"version":asset["version"],"parentId":asset["parent_id"],"metadata":self.runtime.json_value(asset["metadata"],{}),"content":stored,"createdAt":asset["created_at"]}})
