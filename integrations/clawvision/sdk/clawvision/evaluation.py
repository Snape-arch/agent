"""Online-only immutable test manifests and evaluation reports.

Unlike training metric batches, these calls fail explicitly on upload errors;
they do not claim a report exists while an offline request is still queued.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from . import _request, ClawVisionError


class EvaluationClient:
    def __init__(self, base_url=None, api_token=None):
        self.base_url = base_url or os.environ.get("CLAWVISION_API_URL", "http://127.0.0.1:8787")
        self.api_token = api_token

    def _call(self, path, payload=None):
        return _request(self.base_url, "/api/evaluation/" + path, payload,
                        method="POST" if payload is not None else "GET", api_token=self.api_token)

    def create_test_set(self, name, samples, *, classes=None, dataset_version_id=None):
        payload = {"name": name, "task": "classification", "samples": samples}
        if classes is not None:
            payload["classes"] = classes
        if dataset_version_id is not None:
            payload["datasetVersionId"] = dataset_version_id
        return self._call("test-sets", payload)["data"]

    def evaluate(self, test_set_id, run_id, predictions, *, name=None, model_artifact_id=None):
        payload = {"testSetId": test_set_id, "runId": run_id, "predictions": predictions}
        if name is not None:
            payload["name"] = name
        if model_artifact_id is not None:
            payload["modelArtifactId"] = model_artifact_id
        return self._call("reports", payload)["data"]

    def export_test_set(self, test_set_id):
        return self._call("test-sets/" + quote(test_set_id, safe="") + "/export")["data"]

    def get_report(self, report_id):
        return self._call("reports/" + quote(report_id, safe=""))["data"]

    def failures(self, report_id, *, page=1, page_size=25, dimension=None, value=None):
        query = {"page": page, "pageSize": page_size, "failuresOnly": "true"}
        if dimension is not None:
            query["dimension"] = dimension
        if value is not None:
            query["value"] = value
        return self._call("reports/" + quote(report_id, safe="") + "/cases?" + urlencode(query))

    def compare(self, baseline_id, candidate_id):
        return self._call("compare?" + urlencode({"baselineId": baseline_id, "candidateId": candidate_id}))["data"]

    def create_scene_plan(self, name, report_id, sample_id, asset_id, label, *, config=None, parent_id=None):
        payload = {"name": name, "reportId": report_id, "sampleId": sample_id, "assetId": asset_id, "label": label}
        if config is not None:
            payload["config"] = config
        if parent_id is not None:
            payload["parentId"] = parent_id
        return self._call("scenarios", payload)["data"]

    def scene_plans(self, report_id=None, *, page=1, page_size=25):
        query = {"page": page, "pageSize": page_size}
        if report_id is not None:
            query["reportId"] = report_id
        return self._call("scenarios?" + urlencode(query))

    def get_scene_plan(self, scenario_id):
        return self._call("scenarios/" + quote(scenario_id, safe=""))["data"]

    def export_scene_plan(self, scenario_id):
        return self._call("scenarios/" + quote(scenario_id, safe="") + "/export")["data"]

    def verified_scene_asset(self, scenario_id):
        return self._call("scenarios/" + quote(scenario_id, safe="") + "/asset")["data"]

    def render_scene(self, scenario_id, *, variant_indices=None, min_visible_pixels=64, min_visible_fraction=.2, reject_clipped=True):
        payload = {"minVisiblePixels": min_visible_pixels, "minVisibleFraction": min_visible_fraction, "rejectClipped": reject_clipped}
        if variant_indices is not None:
            payload["variantIndices"] = variant_indices
        return self._call("scenarios/" + quote(scenario_id, safe="") + "/renders", payload)["data"]

    def synthesis_jobs(self, scenario_id, *, page=1, page_size=25):
        return self._call("scenarios/" + quote(scenario_id, safe="") + "/renders?" + urlencode({"page": page, "pageSize": page_size}))

    def register_synthesis_dataset(self, job_id, *, name=None, dataset_id=None):
        payload = {}
        if name is not None: payload["name"] = name
        if dataset_id is not None: payload["datasetId"] = dataset_id
        return self._call("synthesis/"+quote(job_id,safe="")+"/dataset-version",payload)["data"]

    def create_image_dataset(self, name, samples, *, purpose, dataset_id=None):
        payload = {"name":name,"samples":samples,"purpose":purpose}
        if dataset_id is not None: payload["datasetId"] = dataset_id
        return self._call("image-datasets",payload)["data"]

    def image_versions(self, *, page=1, page_size=25):
        return self._call("image-versions?"+urlencode({"page":page,"pageSize":page_size}))

    def get_image_version(self, version_id):
        return self._call("image-versions/"+quote(version_id,safe=""))["data"]

    def create_training_comparison(self, real_train_version_id, synthetic_version_id, test_version_id, *, config=None):
        return self._call("experiments",{"realTrainVersionId":real_train_version_id,"syntheticVersionId":synthetic_version_id,
            "testVersionId":test_version_id,"config":config or {}})["data"]

    def training_comparisons(self, *, page=1, page_size=25):
        return self._call("experiments?"+urlencode({"page":page,"pageSize":page_size}))

    def get_training_comparison(self, experiment_id):
        return self._call("experiments/"+quote(experiment_id,safe=""))["data"]

    def cancel_training_comparison(self, experiment_id):
        return self._call("experiments/"+quote(experiment_id,safe="")+"/cancel",{})["data"]

    def retry_training_comparison(self, experiment_id):
        return self._call("experiments/"+quote(experiment_id,safe="")+"/retry",{})["data"]

    def get_synthesis_job(self, job_id):
        return self._call("synthesis/" + quote(job_id, safe=""))["data"]

    def synthesis_frames(self, job_id, *, page=1, page_size=25):
        return self._call("synthesis/" + quote(job_id, safe="") + "/frames?" + urlencode({"page": page, "pageSize": page_size}))

    def synthesis_manifest(self, job_id):
        return self._call("synthesis/" + quote(job_id, safe="") + "/manifest")["data"]

    def cancel_synthesis(self, job_id):
        return self._call("synthesis/" + quote(job_id, safe="") + "/cancel", {})["data"]

    def retry_synthesis(self, job_id):
        return self._call("synthesis/" + quote(job_id, safe="") + "/retry", {})["data"]

    def download_synthesis_package(self, job_id):
        """Return ZIP bytes; online-only, bounded to 65 MB including metadata."""
        token = self.api_token or os.environ.get("CLAWVISION_API_TOKEN")
        request = urllib.request.Request(self.base_url.rstrip('/') + "/api/evaluation/synthesis/" + quote(job_id, safe="") + "/export",
                                         headers={"Authorization": "Bearer " + token} if token else {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = response.read(65 * 1024 * 1024 + 1)
                if len(value) > 65 * 1024 * 1024 or response.headers.get_content_type() != "application/zip":
                    raise ClawVisionError("invalid or oversized synthetic ZIP response")
                return value
        except urllib.error.URLError as error:
            if isinstance(error, urllib.error.HTTPError): error.close()
            raise ClawVisionError(f"synthetic package download failed: {error}") from error
