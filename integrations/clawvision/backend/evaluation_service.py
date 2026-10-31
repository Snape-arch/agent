"""Bounded, tenant-scoped evaluation of uploaded single-label predictions.

This service measures submitted predictions; it never runs inference or claims
that external image bytes are frozen by an immutable manifest.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

from api_contract import Pagination, page_meta
from errors import NotFoundError, ValidationError

MAX_SAMPLES = 5000
MAX_GROUPS = 200


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(value, field, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def insert_rows(db, table, columns, rows):
    # Bound parameters and round trips on both SQLite and PostgreSQL.
    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        placeholders = "(" + ",".join("?" for _ in columns) + ")"
        db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES " + ",".join(placeholders for _ in batch),
                   tuple(value for row in batch for value in row))


def summarize(samples, predictions, classes):
    confusion = Counter((sample["label"], predictions[sample["id"]]["label"]) for sample in samples)
    correct = sum(count for (actual, predicted), count in confusion.items() if actual == predicted)
    class_metrics = []
    for label in classes:
        tp = confusion[label, label]
        support = sum(count for (actual, _), count in confusion.items() if actual == label)
        predicted_count = sum(count for (_, predicted), count in confusion.items() if predicted == label)
        class_metrics.append({"label": label, "support": support,
                              "precision": tp / predicted_count if predicted_count else None,
                              "recall": tp / support if support else None,
                              "f1": 2 * tp / (support + predicted_count) if support + predicted_count else None})
    groups = {}
    for sample in samples:
        for dimension, value in sample["conditions"].items():
            counts = groups.setdefault((dimension, value), [0, 0])
            counts[0] += 1
            counts[1] += int(sample["label"] != predictions[sample["id"]]["label"])
    active_f1 = [item["f1"] for item in class_metrics if item["f1"] is not None]
    return {"total": len(samples), "correct": correct, "errors": len(samples) - correct,
            "accuracy": correct / len(samples), "errorRate": 1 - correct / len(samples),
            "macroF1": sum(active_f1) / len(active_f1), "classMetrics": class_metrics,
            "confusion": [{"actual": actual, "predicted": predicted, "count": count}
                          for (actual, predicted), count in sorted(confusion.items())],
            "groups": [{"dimension": dimension, "value": value, "total": counts[0], "errors": counts[1],
                        "errorRate": counts[1] / counts[0]} for (dimension, value), counts in sorted(groups.items())]}


class EvaluationService:
    def __init__(self, connect, prediction_origin="uploaded-predictions"):
        self.connect = connect
        self.prediction_origin = prediction_origin

    @staticmethod
    def _set(db, tenant_id, set_id):
        row = db.execute("SELECT * FROM evaluation_test_sets WHERE id=? AND tenant_id=?", (set_id, tenant_id)).fetchone()
        if not row:
            raise NotFoundError("test set not found")
        return row

    @staticmethod
    def _evaluation(db, tenant_id, evaluation_id):
        row = db.execute("SELECT * FROM evaluations WHERE id=? AND tenant_id=?", (evaluation_id, tenant_id)).fetchone()
        if not row:
            raise NotFoundError("evaluation not found")
        return row

    @staticmethod
    def _set_json(row):
        return {"id": row["id"], "name": row["name"], "task": row["task"], "digest": row["digest"],
                "classes": json.loads(row["classes_json"]), "sampleCount": row["sample_count"],
                "datasetVersionId": row["dataset_version_id"], "createdAt": row["created_at"]}

    @staticmethod
    def _evaluation_json(row):
        return {"id": row["id"], "name": row["name"], "testSetId": row["test_set_id"], "runId": row["run_id"],
                "digest": row["digest"], "summary": json.loads(row["summary_json"]),
                "provenance": json.loads(row["provenance_json"]), "createdAt": row["created_at"]}

    def create_test_set(self, tenant_id, request):
        name = text(request.get("name"), "name", 200)
        if request.get("task", "classification") != "classification":
            raise ValidationError("only single-label classification is supported")
        raw_samples = request.get("samples")
        if not isinstance(raw_samples, list) or not 1 <= len(raw_samples) <= MAX_SAMPLES:
            raise ValidationError(f"samples must contain 1 to {MAX_SAMPLES} records")
        samples, ids, groups = [], set(), set()
        for raw in raw_samples:
            if not isinstance(raw, dict):
                raise ValidationError("each sample must be an object")
            sample_id, label = text(raw.get("id"), "sample.id"), text(raw.get("label"), "sample.label")
            if sample_id in ids:
                raise ValidationError(f"duplicate sample id: {sample_id}")
            ids.add(sample_id)
            raw_conditions = raw.get("conditions", {})
            if not isinstance(raw_conditions, dict) or len(raw_conditions) > 8:
                raise ValidationError("conditions must be an object with at most 8 dimensions")
            conditions = {text(key, "condition dimension", 64): text(value, "condition value") for key, value in raw_conditions.items()}
            if len(conditions) != len(raw_conditions):
                raise ValidationError("condition dimensions must be unique after trimming")
            groups.update(conditions.items())
            if len(groups) > MAX_GROUPS:
                raise ValidationError(f"test set exceeds {MAX_GROUPS} condition groups; bucket continuous values first")
            image_uri = text(raw["imageUri"], "imageUri", 2048) if raw.get("imageUri") is not None else None
            content_hash = raw.get("contentHash")
            if content_hash is not None and (not isinstance(content_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", content_hash)):
                raise ValidationError("contentHash must be a SHA-256 hex digest")
            samples.append({"id": sample_id, "label": label, "conditions": conditions, "imageUri": image_uri,
                            "contentHash": content_hash.lower() if content_hash else None})
        samples.sort(key=lambda item: item["id"])
        raw_classes = request.get("classes", sorted({sample["label"] for sample in samples}))
        if not isinstance(raw_classes, list) or not 1 <= len(raw_classes) <= 100:
            raise ValidationError("classes must contain 1 to 100 labels")
        classes = sorted(text(value, "class label") for value in raw_classes)
        if len(set(classes)) != len(classes) or not {sample["label"] for sample in samples}.issubset(classes):
            raise ValidationError("classes must be unique and include every ground-truth label")
        version_id = text(request["datasetVersionId"], "datasetVersionId") if request.get("datasetVersionId") is not None else None
        manifest = {"task": "classification", "classes": classes, "samples": samples, "datasetVersionId": version_id}
        if len(canonical(manifest).encode()) > 8 * 1024 * 1024:
            raise ValidationError("test manifest exceeds 8 MB")
        set_id, created = "evalset_" + uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if version_id and not db.execute("SELECT 1 FROM dataset_versions WHERE id=? AND tenant_id=?", (version_id, tenant_id)).fetchone():
                raise NotFoundError("dataset version not found")
            db.execute("INSERT INTO evaluation_test_sets(id,tenant_id,name,task,digest,classes_json,sample_count,dataset_version_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (set_id, tenant_id, name, "classification", digest(manifest), canonical(classes), len(samples), version_id, created))
            insert_rows(db, "evaluation_samples", ("test_set_id", "sample_id", "label", "image_uri", "content_hash", "conditions_json"),
                        [(set_id, sample["id"], sample["label"], sample["imageUri"], sample["contentHash"], canonical(sample["conditions"])) for sample in samples])
            insert_rows(db, "evaluation_conditions", ("test_set_id", "sample_id", "dimension", "value"),
                        [(set_id, sample["id"], key, value) for sample in samples for key, value in sample["conditions"].items()])
            return self._set_json(self._set(db, tenant_id, set_id))

    def list_test_sets(self, tenant_id, pagination):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) AS count FROM evaluation_test_sets WHERE tenant_id=?", (tenant_id,)).fetchone()["count"]
            rows = db.execute("SELECT * FROM evaluation_test_sets WHERE tenant_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              (tenant_id, pagination.page_size, pagination.offset)).fetchall()
        return {"data": [self._set_json(row) for row in rows], "pagination": page_meta(pagination, total)}

    def get_test_set(self, tenant_id, set_id):
        with self.connect() as db:
            return self._set_json(self._set(db, tenant_id, set_id))

    @staticmethod
    def _samples(db, set_id):
        return [{"id": row["sample_id"], "label": row["label"], "conditions": json.loads(row["conditions_json"]),
                 "imageUri": row["image_uri"], "contentHash": row["content_hash"]}
                for row in db.execute("SELECT * FROM evaluation_samples WHERE test_set_id=? ORDER BY sample_id", (set_id,)).fetchall()]

    def export_test_set(self, tenant_id, set_id):
        with self.connect() as db:
            return {**self._set_json(self._set(db, tenant_id, set_id)), "samples": self._samples(db, set_id)}

    def create_evaluation(self, tenant_id, request):
        set_id, run_id = text(request.get("testSetId"), "testSetId"), text(request.get("runId"), "runId")
        with self.connect() as db:
            test_set = self._set(db, tenant_id, set_id)
            run = db.execute("SELECT * FROM runs WHERE id=? AND tenant_id=?", (run_id, tenant_id)).fetchone()
            if not run:
                raise NotFoundError("run not found")
            samples, classes = self._samples(db, set_id), json.loads(test_set["classes_json"])
            raw_predictions = request.get("predictions")
            if not isinstance(raw_predictions, list) or len(raw_predictions) != len(samples):
                raise ValidationError("predictions must cover every test sample exactly once")
            predictions = {}
            for raw in raw_predictions:
                if not isinstance(raw, dict):
                    raise ValidationError("each prediction must be an object")
                sample_id, label = text(raw.get("sampleId"), "sampleId"), text(raw.get("label"), "predicted label")
                confidence = raw.get("confidence")
                if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                    raise ValidationError("confidence must be a finite number between 0 and 1")
                if sample_id in predictions or label not in classes:
                    raise ValidationError("prediction sample IDs must be unique and labels must belong to test-set classes")
                predictions[sample_id] = {"label": label, "confidence": confidence}
            if set(predictions) != {sample["id"] for sample in samples}:
                raise ValidationError("prediction IDs do not match the frozen test manifest")
            artifact_id = request.get("modelArtifactId")
            artifact = None
            if artifact_id is not None:
                artifact_id = text(artifact_id, "modelArtifactId")
                artifact = db.execute("SELECT id,name,type,created_at FROM artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)).fetchone()
                if not artifact:
                    raise NotFoundError("model artifact does not belong to this run")
            summary = summarize(samples, predictions, classes)
            provenance = {"kind": self.prediction_origin, "testSetDigest": test_set["digest"], "datasetVersionId": test_set["dataset_version_id"],
                          "run": {"id": run_id, "name": run["name"], "source": run["source"], "status": run["status"],
                                  "revision": run["revision"], "params": json.loads(run["params"])},
                          "modelArtifact": dict(artifact) if artifact else None}
            evaluation_id, created = "eval_" + uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
            name = text(request.get("name", run["name"]), "name", 200)
            result_digest = digest({"testSetDigest": test_set["digest"], "provenance": provenance, "predictions": predictions})
            db.execute("INSERT INTO evaluations(id,tenant_id,test_set_id,run_id,name,digest,summary_json,provenance_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (evaluation_id, tenant_id, set_id, run_id, name, result_digest, canonical(summary), canonical(provenance), created))
            insert_rows(db, "evaluation_predictions", ("evaluation_id", "sample_id", "predicted_label", "confidence", "correct"),
                        [(evaluation_id, sample["id"], predictions[sample["id"]]["label"], predictions[sample["id"]]["confidence"],
                          int(sample["label"] == predictions[sample["id"]]["label"])) for sample in samples])
            return self._evaluation_json(self._evaluation(db, tenant_id, evaluation_id))

    def list_evaluations(self, tenant_id, pagination, set_id=None):
        with self.connect() as db:
            where, values = "tenant_id=?", [tenant_id]
            if set_id:
                self._set(db, tenant_id, set_id)
                where += " AND test_set_id=?"
                values.append(set_id)
            total = db.execute(f"SELECT COUNT(*) AS count FROM evaluations WHERE {where}", tuple(values)).fetchone()["count"]
            rows = db.execute(f"SELECT * FROM evaluations WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              (*values, pagination.page_size, pagination.offset)).fetchall()
        return {"data": [self._evaluation_json(row) for row in rows], "pagination": page_meta(pagination, total)}

    def get_evaluation(self, tenant_id, evaluation_id):
        with self.connect() as db:
            return self._evaluation_json(self._evaluation(db, tenant_id, evaluation_id))

    def cases(self, tenant_id, evaluation_id, pagination, *, failures_only=True, dimension=None, value=None):
        with self.connect() as db:
            evaluation = self._evaluation(db, tenant_id, evaluation_id)
            where, values = "p.evaluation_id=? AND s.test_set_id=?", [evaluation_id, evaluation["test_set_id"]]
            if failures_only:
                where += " AND p.correct=0"
            if (dimension is None) != (value is None):
                raise ValidationError("dimension and value must be supplied together")
            if dimension is not None:
                where += " AND EXISTS(SELECT 1 FROM evaluation_conditions c WHERE c.test_set_id=s.test_set_id AND c.sample_id=s.sample_id AND c.dimension=? AND c.value=?)"
                values.extend([text(dimension, "dimension", 64), text(value, "value")])
            source = "evaluation_predictions p JOIN evaluation_samples s ON s.sample_id=p.sample_id"
            total = db.execute(f"SELECT COUNT(*) AS count FROM {source} WHERE {where}", tuple(values)).fetchone()["count"]
            rows = db.execute(f"SELECT s.*,p.predicted_label,p.confidence,p.correct FROM {source} WHERE {where} ORDER BY s.sample_id LIMIT ? OFFSET ?",
                              (*values, pagination.page_size, pagination.offset)).fetchall()
        return {"data": [{"sampleId": row["sample_id"], "label": row["label"], "predictedLabel": row["predicted_label"],
                          "confidence": row["confidence"], "correct": bool(row["correct"]), "conditions": json.loads(row["conditions_json"]),
                          "imageUri": row["image_uri"], "contentHash": row["content_hash"]} for row in rows], "pagination": page_meta(pagination, total)}

    def compare(self, tenant_id, baseline_id, candidate_id):
        with self.connect() as db:
            baseline = self._evaluation(db, tenant_id, baseline_id)
            candidate = self._evaluation(db, tenant_id, candidate_id)
            if baseline["test_set_id"] != candidate["test_set_id"]:
                raise ValidationError("comparison requires the same frozen test set")
            if baseline["run_id"] == candidate["run_id"]:
                raise ValidationError("comparison requires two different Runs")
            transitions = db.execute("SELECT a.correct AS before_correct,b.correct AS after_correct,COUNT(*) AS count FROM evaluation_predictions a JOIN evaluation_predictions b ON a.sample_id=b.sample_id WHERE a.evaluation_id=? AND b.evaluation_id=? GROUP BY a.correct,b.correct",
                                     (baseline_id, candidate_id)).fetchall()
        counts = {(row["before_correct"], row["after_correct"]): row["count"] for row in transitions}
        left, right = self._evaluation_json(baseline), self._evaluation_json(candidate)
        left_groups = {(group["dimension"], group["value"]): group for group in left["summary"]["groups"]}
        group_changes = [{**group, "baselineErrors": left_groups[group["dimension"], group["value"]]["errors"],
                          "errorRateDelta": group["errorRate"] - left_groups[group["dimension"], group["value"]]["errorRate"]}
                         for group in right["summary"]["groups"]]
        return {"baseline": left, "candidate": right, "testSetId": baseline["test_set_id"],
                "accuracyDelta": right["summary"]["accuracy"] - left["summary"]["accuracy"],
                "errorRateDelta": right["summary"]["errorRate"] - left["summary"]["errorRate"],
                "macroF1Delta": right["summary"]["macroF1"] - left["summary"]["macroF1"],
                "fixed": counts.get((0, 1), 0), "regressed": counts.get((1, 0), 0),
                "bothCorrect": counts.get((1, 1), 0), "bothWrong": counts.get((0, 0), 0), "groups": group_changes}
