"""Immutable image versions backed by the existing Parquet dataset catalog."""
import base64
import hashlib
import json
import uuid
from contextlib import nullcontext

from analytics_service import DatasetCatalog
from api_contract import page_meta
from columnar_engine import rows_to_parquet
from errors import ConflictError, NotFoundError, ValidationError
from evaluation_service import canonical, digest, text
from security import reserve_storage
from synthesis_service import SynthesisService, now
import vision_model

MAX_BYTES = 64*1024*1024

class VisionDatasetService:
    def __init__(self, connect, store, lock):
        self.connect, self.store, self.lock = connect, store, lock

    @staticmethod
    def _row(db, tenant, version_id):
        row = db.execute("SELECT v.*,d.dataset_id,d.version,s.name FROM vision_dataset_versions v JOIN dataset_versions d ON d.id=v.version_id JOIN datasets s ON s.id=d.dataset_id WHERE v.version_id=? AND v.tenant_id=?", (version_id,tenant)).fetchone()
        if not row: raise NotFoundError("image dataset version not found")
        return row

    @staticmethod
    def _json(row, full=False):
        manifest = json.loads(row["manifest_json"])
        result = {"id":row["version_id"],"datasetId":row["dataset_id"],"version":row["version"],"name":row["name"],
                  "origin":row["origin"],"purpose":row["purpose"],"digest":row["digest"],"sampleCount":len(manifest["samples"]),
                  "classes":manifest["classes"],"sourceJobId":row["source_job_id"],"createdAt":row["created_at"]}
        if full: result["manifest"] = manifest
        return result

    def get(self, tenant, version_id):
        with self.connect() as db: row = self._row(db,tenant,version_id)
        result = self._json(row,True)
        if digest(result["manifest"]) != result["digest"]: raise ConflictError("image version manifest hash changed")
        return result

    def list(self, tenant, pagination):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) AS n FROM vision_dataset_versions WHERE tenant_id=?",(tenant,)).fetchone()["n"]
            rows = db.execute("SELECT v.*,d.dataset_id,d.version,s.name FROM vision_dataset_versions v JOIN dataset_versions d ON d.id=v.version_id JOIN datasets s ON s.id=d.dataset_id WHERE v.tenant_id=? ORDER BY v.created_at DESC,v.version_id DESC LIMIT ? OFFSET ?",(tenant,pagination.page_size,pagination.offset)).fetchall()
        return {"data":[self._json(row) for row in rows],"pagination":page_meta(pagination,total)}

    def _verified(self, info):
        try:
            if info["byteSize"] > MAX_BYTES or self.store.byte_size(info["key"]) != info["byteSize"]: raise ConflictError("image bytes changed")
            content = self.store.get_bytes(info["key"])
        except FileNotFoundError as error: raise ConflictError("image object is missing") from error
        if hashlib.sha256(content).hexdigest() != info["sha256"]: raise ConflictError("image hash changed")
        return content

    def image(self, tenant, version_id, index):
        samples = self.get(tenant,version_id)["manifest"]["samples"]
        if not 0 <= index < len(samples): raise NotFoundError("image not found")
        return self._verified(samples[index]["image"])

    def create_real(self, tenant, body):
        if not isinstance(body,dict) or set(body)-{"name","datasetId","purpose","samples"}: raise ValidationError("invalid image dataset fields")
        purpose = body.get("purpose")
        if purpose not in {"train","test"}: raise ValidationError("purpose must be train or test")
        raw = body.get("samples")
        if not isinstance(raw,list) or not 1 <= len(raw) <= 512: raise ValidationError("upload 1 to 512 real images")
        samples, objects, ids, hashes, total = [], [], set(), set(), 0
        for item in raw:
            if not isinstance(item,dict) or set(item)-{"id","label","imageBase64","conditions"}: raise ValidationError("invalid real image fields")
            sample_id, label = text(item.get("id"),"sample.id"), text(item.get("label"),"sample.label")
            try:
                encoded = item["imageBase64"]
                if not isinstance(encoded,str) or len(encoded) > 3*1024*1024: raise ValueError("image exceeds 2 MiB")
                content = base64.b64decode(encoded,validate=True)
                if not content or len(content) > 2*1024*1024: raise ValueError("image exceeds 2 MiB")
            except (KeyError,ValueError) as error: raise ValidationError("imageBase64 must contain a PNG/JPEG of at most 2 MiB") from error
            normalized, pixel_hash = vision_model.image_data(content)
            if sample_id in ids or pixel_hash in hashes: raise ValidationError("duplicate sample ID or decoded image pixels")
            ids.add(sample_id); hashes.add(pixel_hash)
            conditions = item.get("conditions",{})
            if not isinstance(conditions,dict) or len(conditions)>8: raise ValidationError("conditions must contain at most 8 dimensions")
            conditions = {text(k,"condition",64):text(v,"value") for k,v in conditions.items()}
            total += len(normalized)
            if total > MAX_BYTES: raise ValidationError("image dataset exceeds 64 MiB")
            sha = hashlib.sha256(normalized).hexdigest()
            key = f"tenants/{tenant}/vision/images/{uuid.uuid4().hex}.png"
            samples.append({"id":sample_id,"label":label,"conditions":conditions,"pixelHash":pixel_hash,
                            "originalSha256":hashlib.sha256(content).hexdigest(),"image":{"key":key,"sha256":sha,"byteSize":len(normalized)}})
            objects.append((key,normalized))
        signatures = [{k:v for k,v in s.items() if k!="image"} | {"sha256":s["image"]["sha256"]} for s in samples]
        signature = digest({"origin":"real","purpose":purpose,"datasetId":body.get("datasetId"),"samples":signatures})
        return self._register(tenant,body,"real",purpose,samples,signature,objects)

    def from_synthesis(self, tenant, job_id, body):
        if not isinstance(body,dict) or set(body)-{"name","datasetId"}: raise ValidationError("invalid synthesis registration fields")
        result = SynthesisService(self.connect,self.store,self.lock).manifest(tenant,job_id)
        samples = []
        for frame in result["manifest"]["frames"]:
            if not frame["accepted"]: continue
            image = frame["artifacts"]["image"]
            _, pixel_hash = vision_model.image_data(self._verified(image))
            samples.append({"id":str(frame["variantIndex"]),"label":frame["annotation"]["label"],"conditions":{},"pixelHash":pixel_hash,
                            "originalSha256":image["sha256"],"image":image})
        if not samples: raise ValidationError("cannot register an empty accepted synthetic dataset")
        signature = digest({"sourceJobId":job_id,"digest":result["digest"],"datasetId":body.get("datasetId")})
        return self._register(tenant,body,"synthetic","train",samples,signature,[],job_id,
                              {"synthesisDigest":result["digest"],"source":result["manifest"]["source"],"scenarioDigest":result["manifest"]["scenarioDigest"]})

    def _register(self, tenant, body, origin, purpose, samples, signature, objects, source_job=None, lineage=None):
        name = text(body.get("name", "真实图片" if origin=="real" else "合成图片"),"name",200)
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT version_id FROM vision_dataset_versions WHERE tenant_id=? AND request_digest=?",(tenant,signature)).fetchone()
            if existing: return self._json(self._row(db,tenant,existing["version_id"]),True)
            dataset_id = body.get("datasetId")
            if dataset_id:
                current = db.execute("SELECT d.id,v.origin,v.purpose FROM datasets d JOIN vision_dataset_versions v ON v.version_id=d.current_version_id WHERE d.id=? AND d.tenant_id=?",(text(dataset_id,"datasetId"),tenant)).fetchone()
                if not current: raise NotFoundError("image dataset not found")
                if (current["origin"],current["purpose"]) != (origin,purpose): raise ValidationError("image dataset origin and purpose cannot change")
            else: dataset_id = "data_"+uuid.uuid4().hex[:16]
            rows = [{"id":s["id"],"label":s["label"],"sha256":s["image"]["sha256"],"pixelHash":s["pixelHash"],"origin":origin,"purpose":purpose,
                     "imageKey":s["image"]["key"],"conditions":canonical(s["conditions"]),"sourceJobId":source_job or ""} for s in samples]
            schema = [{"name":k,"type":"string"} for k in rows[0]]
            parquet = rows_to_parquet(rows)
            if parquet is None: raise ValidationError("image version registration requires pyarrow")
            prefix = f"tenants/{tenant}/datasets/{dataset_id}/vision/{uuid.uuid4().hex}"
            preview, parquet_key = prefix+"/preview.json",prefix+"/samples.parquet"
            preview_bytes = canonical(rows).encode()
            reserve_storage(tenant,sum(len(v) for _,v in objects)+len(parquet)+len(preview_bytes))
            for key, content in objects: self.store.put_bytes(key,content,"image/png")
            self.store.put_bytes(preview,preview_bytes,"application/json"); self.store.put_bytes(parquet_key,parquet)
            timestamp = now()
            if not body.get("datasetId"):
                db.execute("INSERT INTO datasets(id,tenant_id,name,format,schema_json,object_key,row_count,created_at,updated_at) VALUES(?,?,?,'json','[]',?,0,?,?)",(dataset_id,tenant,name,preview,timestamp,timestamp))
            catalog = DatasetCatalog(lambda: nullcontext(db),self.store)
            version = catalog.register_version(dataset_id,tenant,schema,[{"key":parquet_key,"format":"parquet","rowCount":len(rows),"byteSize":len(parquet),"sha256":hashlib.sha256(parquet).hexdigest(),"partitions":{}}])
            manifest = {"schemaVersion":"clawvision.image-dataset/1","origin":origin,"purpose":purpose,"classes":sorted({s["label"] for s in samples}),
                        "samples":samples,"catalogVersionId":version["id"],"lineage":lineage or {}}
            db.execute("UPDATE datasets SET object_key=? WHERE id=?",(preview,dataset_id))
            db.execute("INSERT INTO vision_dataset_versions(version_id,tenant_id,origin,purpose,digest,manifest_json,request_digest,source_job_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (version["id"],tenant,origin,purpose,digest(manifest),canonical(manifest),signature,source_job,timestamp))
            return self._json(self._row(db,tenant,version["id"]),True)
