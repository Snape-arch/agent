"""Freeze a failure, actual asset bytes and a bounded deterministic scene plan.

Plans do not contain rendered images or verified synthetic ground truth.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from api_contract import page_meta
from errors import ConflictError, NotFoundError, ValidationError
from evaluation_service import EvaluationService, canonical, digest, text

MAX_ASSET_BYTES = 16 * 1024 * 1024
RANGES = {
    "cameraAzimuth": (-180, 180, [-40, 40]),
    "cameraElevation": (-80, 80, [10, 40]),
    "cameraDistance": (1.5, 10, [3, 4]),
    "lightAzimuth": (-180, 180, [-60, 60]),
    "lightElevation": (-80, 80, [20, 70]),
    "lightIntensity": (0, 10, [1, 3]),
    "roughness": (0, 1, [.2, .8]),
    "metalness": (0, 1, [0, .7]),
    "occluderSize": (0, 1.5, [0, .5]),
}


def integer(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def normalize_config(raw):
    if not isinstance(raw, dict) or set(raw) - {"seed", "count", "ranges", "materialColor", "background"}:
        raise ValidationError("config contains unknown fields or is not an object")
    ranges = raw.get("ranges", {})
    if not isinstance(ranges, dict) or set(ranges) - set(RANGES):
        raise ValidationError("ranges must use supported scene parameter names")
    result = {"seed": integer(raw.get("seed", 42), "seed", 0, 2**32 - 1),
              "count": integer(raw.get("count", 12), "count", 1, 256), "ranges": {}}
    for key, (minimum, maximum, default) in RANGES.items():
        values = ranges.get(key, default)
        if (not isinstance(values, list) or len(values) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not minimum <= v <= maximum for v in values) or
                not minimum <= values[0] <= values[1] <= maximum):
            raise ValidationError(f"{key} must be [min,max] within [{minimum},{maximum}]")
        result["ranges"][key] = [round(v, 6) for v in values]
    for key, default in (("materialColor", "#7cf7c8"), ("background", "#152620")):
        value = raw.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", value):
            raise ValidationError(f"{key} must be a six-digit hex color")
        result[key] = value.lower()
    return result


def variants(config):
    # Stable across Python versions. The persisted output is the replay authority.
    result = []
    for index in range(config["count"]):
        parameters = {}
        for key, (low, high) in sorted(config["ranges"].items()):
            raw = hashlib.sha256(f"{config['seed']}:{index}:{key}".encode("ascii")).digest()
            unit = int.from_bytes(raw[:8], "big") / 2**64
            parameters[key] = round(low + (high - low) * unit, 6)
        result.append({"index": index, "parameters": parameters})
    return result


class ScenarioService:
    def __init__(self, connect, object_store, lock):
        self.connect, self.object_store, self.lock = connect, object_store, lock

    @staticmethod
    def _row(db, tenant, scenario_id):
        row = db.execute("SELECT * FROM evaluation_scenarios WHERE id=? AND tenant_id=?", (scenario_id, tenant)).fetchone()
        if not row:
            raise NotFoundError("scenario not found")
        return row

    @staticmethod
    def _json(row, full=False):
        manifest = json.loads(row["manifest_json"])
        result = {"id": row["id"], "name": row["name"], "reportId": row["report_id"], "assetId": row["asset_id"],
                  "parentId": row["parent_id"], "version": row["version"], "digest": row["digest"],
                  "createdAt": row["created_at"], "source": manifest["source"], "asset": manifest["asset"],
                  "variantCount": len(manifest["variants"])}
        if full:
            result["manifest"] = manifest
        return result

    def _asset_bytes(self, row):
        store = self.object_store
        # The JSON envelope can contain base64; bound it before reading it.
        try:
            if store.byte_size(row["object_key"]) > 24 * 1024 * 1024:
                raise ValidationError("asset envelope exceeds 24 MB; use a self-contained asset up to 16 MB")
            stored = store.get_json(row["object_key"])
            if not isinstance(stored, dict):
                raise ConflictError("asset envelope is invalid")
            if stored.get("resources"):
                raise ValidationError("scene plans require self-contained GLB, OBJ or STL without sidecar resources")
            if stored.get("binaryKey"):
                if store.byte_size(stored["binaryKey"]) > MAX_ASSET_BYTES:
                    raise ValidationError("scene asset exceeds 16 MB")
                content = store.get_bytes(stored["binaryKey"])
            else:
                content = base64.b64decode(stored["base64"], validate=True)
        except (FileNotFoundError, KeyError, binascii.Error, ValueError) as error:
            raise ConflictError("asset content is missing or invalid") from error
        if not content or len(content) > MAX_ASSET_BYTES:
            raise ValidationError("scene asset must contain 1 byte to 16 MB")
        return content

    def create(self, tenant, request):
        if not isinstance(request, dict) or set(request) - {"name", "reportId", "sampleId", "assetId", "label", "config", "parentId"}:
            raise ValidationError("scenario request contains unknown fields or is not an object")
        report_id = text(request.get("reportId"), "reportId")
        sample_id, asset_id = text(request.get("sampleId"), "sampleId"), text(request.get("assetId"), "assetId")
        label, name = text(request.get("label"), "label"), text(request.get("name"), "name", 200)
        config = normalize_config(request.get("config", {}))
        parent_id = text(request["parentId"], "parentId") if request.get("parentId") is not None else None
        with self.lock, self.connect() as db:
            report = EvaluationService._evaluation(db, tenant, report_id)
            sample = db.execute("SELECT s.*,p.predicted_label,p.confidence FROM evaluation_samples s JOIN evaluation_predictions p ON p.sample_id=s.sample_id WHERE s.test_set_id=? AND p.evaluation_id=? AND s.sample_id=? AND p.correct=0",
                                (report["test_set_id"], report_id, sample_id)).fetchone()
            if not sample:
                raise NotFoundError("failure sample not found in this report")
            if label != sample["label"]:
                raise ValidationError("asset label must match the failure's ground-truth label; this is a manual association")
            asset = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (asset_id, tenant)).fetchone()
            if not asset:
                raise NotFoundError("asset not found")
            if asset["format"] not in {"glb", "obj", "stl"}:
                raise ValidationError("convert the asset to self-contained GLB, OBJ or STL before creating a scene plan")
            version = 1
            if parent_id:
                parent = self._row(db, tenant, parent_id)
                if parent["report_id"] != report_id or json.loads(parent["manifest_json"])["source"]["sampleId"] != sample_id:
                    raise ValidationError("a new version must keep the same report and failure sample")
                version = parent["version"] + 1
            content = self._asset_bytes(asset)
            manifest = {
                "schemaVersion": "clawvision.scene-plan/1", "kind": "unrendered-scene-plan", "sampling": "sha256-counter-v1",
                "source": {"reportId": report_id, "reportDigest": report["digest"], "testSetId": report["test_set_id"],
                           "testSetDigest": json.loads(report["provenance_json"])["testSetDigest"], "runId": report["run_id"],
                           "sampleId": sample_id, "label": label, "predictedLabel": sample["predicted_label"],
                           "conditions": json.loads(sample["conditions_json"]), "imageUri": sample["image_uri"],
                           "declaredImageHash": sample["content_hash"], "association": "user-confirmed"},
                "asset": {"id": asset_id, "name": asset["name"], "version": asset["version"], "format": asset["format"],
                          "sha256": hashlib.sha256(content).hexdigest(), "byteSize": len(content)},
                "conventions": {"coordinates": "right-handed-Y-up", "normalization": "axis-aligned-bounds-sphere-radius-1-centered-at-origin",
                                "angles": "degrees; azimuth from +Z toward +X; elevation above XZ plane",
                                "cameraFov": 46, "resolution": [512, 512], "ambientIntensity": .7, "lightColor": "#ffffff",
                                "material": "override-all-meshes-with-standard-PBR", "normals": "preserve-or-compute-vertex-normals", "lightDistance": 5,
                                "occluder": "camera-facing square; size in model radii; center offset +0.35 camera-right; halfway to camera",
                                "occluderColor": "#343434", "colorSpace": "sRGB", "toneMapping": "ACESFilmic", "exposure": 1},
                "config": config, "variants": variants(config),
            }
            scenario_id, created = "scenario_" + uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO evaluation_scenarios(id,tenant_id,report_id,asset_id,parent_id,version,name,digest,manifest_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (scenario_id, tenant, report_id, asset_id, parent_id, version, name, digest(manifest), canonical(manifest), created))
            return self._json(self._row(db, tenant, scenario_id), full=True)

    def list(self, tenant, pagination, report_id=None):
        with self.connect() as db:
            where, values = "tenant_id=?", [tenant]
            if report_id:
                EvaluationService._evaluation(db, tenant, report_id)
                where += " AND report_id=?"
                values.append(report_id)
            total = db.execute(f"SELECT COUNT(*) AS count FROM evaluation_scenarios WHERE {where}", tuple(values)).fetchone()["count"]
            # List summaries only; never fetch all variants for every record.
            rows = db.execute(f"SELECT * FROM evaluation_scenarios WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              (*values, pagination.page_size, pagination.offset)).fetchall()
        return {"data": [self._json(row) for row in rows], "pagination": page_meta(pagination, total)}

    def get(self, tenant, scenario_id):
        with self.connect() as db:
            return self._json(self._row(db, tenant, scenario_id), full=True)

    def preview_asset(self, tenant, scenario_id):
        with self.lock, self.connect() as db:
            scenario = self._json(self._row(db, tenant, scenario_id), full=True)
            row = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (scenario["assetId"], tenant)).fetchone()
            if not row:
                raise NotFoundError("pinned asset not found")
            content = self._asset_bytes(row)
            if (hashlib.sha256(content).hexdigest() != scenario["asset"]["sha256"] or
                    row["version"] != scenario["asset"]["version"] or row["format"] != scenario["asset"]["format"]):
                raise ConflictError("pinned asset no longer matches the scene manifest")
        return {"assetId": scenario["assetId"], "format": scenario["asset"]["format"],
                "sha256": scenario["asset"]["sha256"], "base64": base64.b64encode(content).decode("ascii")}
