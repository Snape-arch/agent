"""Version registration, real fitting, leakage guards and checkpoint fencing."""
import base64
import json
import unittest
from unittest.mock import patch

import test_synthesis_service as synthesis_tests
import database
import durable_queue
import vision_model
from api_contract import Pagination
from errors import ConflictError, NotFoundError, ValidationError
from synthesis_service import LeaseLost
from vision_dataset_service import VisionDatasetService
from vision_experiment_service import VisionExperimentService
from synthetic_renderer import png, numpy

def samples(colors, prefix="sample"):
    return [{"id":prefix+str(i),"label":label,"imageBase64":base64.b64encode(png(numpy().broadcast_to(color,(24,24,3)))).decode(),
             "conditions":{"lighting":"test"}} for i,(label,color) in enumerate(colors)]

TRAIN = [("gear",[20,210,140]),("gear",[30,230,150]),("bolt",[190,30,180]),("bolt",[210,40,190])]
TEST = [("gear",[25,220,145]),("bolt",[200,35,185])]

class VisionTrainingTests(unittest.TestCase):
    setUpSynthesis = synthesis_tests.SynthesisServiceTests.setUp
    setUpScene = synthesis_tests.SynthesisServiceTests.setUpScene
    asset = synthesis_tests.SynthesisServiceTests.asset
    tearDown = synthesis_tests.SynthesisServiceTests.tearDown

    def setUp(self):
        self.setUpSynthesis()
        job = self.service.create("default",self.plan["id"],{"variantIndices":[0]})
        durable_queue.lease(job["taskId"],"synth")
        result = self.service.execute("default",job["id"],"synth"); durable_queue.finish(job["taskId"],"synth",result)
        self.job_id = job["id"]
        self.datasets = VisionDatasetService(database.connect,self.store,self.lock)
        self.synthetic = self.datasets.from_synthesis("default",job["id"],{"name":"synth"})
        self.real = self.datasets.create_real("default",{"name":"real train","purpose":"train","samples":samples(TRAIN)})
        self.test = self.datasets.create_real("default",{"name":"real test","purpose":"test","samples":samples(TEST)})
        self.experiments = VisionExperimentService(database.connect,self.store,self.lock)
        self.request = {"realTrainVersionId":self.real["id"],"syntheticVersionId":self.synthetic["id"],"testVersionId":self.test["id"],"config":{"epochs":8}}

    def run_experiment(self, job, owner="cpu"):
        self.assertTrue(durable_queue.lease(job["taskId"],owner))
        result = self.experiments.execute("default",job["id"],owner)
        durable_queue.finish(job["taskId"],owner,result)
        return self.experiments.get("default",job["id"])

    def test_catalog_registration_and_versions_are_immutable_idempotent_and_readable(self):
        same = self.datasets.from_synthesis("default",self.job_id,{})
        self.assertEqual(same["id"],self.synthetic["id"])
        again = self.datasets.create_real("default",{"name":"rename","purpose":"train","samples":samples(TRAIN)})
        self.assertEqual(again["id"],self.real["id"])
        newer = self.datasets.create_real("default",{"name":"real v2","datasetId":self.real["datasetId"],"purpose":"train","samples":samples(TRAIN+[('gear',[40,240,170])])})
        self.assertEqual(newer["version"],2)
        self.assertEqual(self.datasets.get("default",self.real["id"])["sampleCount"],4)
        with database.connect() as db:
            row = db.execute("SELECT row_count,current_version_id,storage_format FROM datasets WHERE id=?",(self.real["datasetId"],)).fetchone()
            self.assertEqual((row["row_count"],row["current_version_id"],row["storage_format"]),(5,newer["id"],"parquet"))
        page = self.datasets.list("default",Pagination(1,2))
        self.assertEqual(page["pagination"]["total"],4); self.assertEqual(len(page["data"]),2)
        self.assertTrue(self.datasets.image("default",self.real["id"],0).startswith(b"\x89PNG"))
        for function,args in ((self.datasets.get,(self.real["id"],)),(self.datasets.image,(self.real["id"],0)),(self.datasets.from_synthesis,(self.job_id,{}))):
            with self.assertRaises(NotFoundError): function("other",*args)

    def test_actual_gradient_fitting_creates_two_models_reports_and_reproducible_comparison(self):
        job = self.experiments.create("default",self.request)
        self.assertEqual(job["id"],self.experiments.create("default",self.request)["id"])
        done = self.run_experiment(job)
        self.assertEqual((done["status"],done["epochsCompleted"]),("completed",16))
        result = done["result"]
        self.assertEqual(result["trainingSamples"],{"baseline":4,"candidate":5})
        self.assertEqual(result["baseline"]["testSetId"],result["candidate"]["testSetId"])
        self.assertNotEqual(result["baseline"]["runId"],result["candidate"]["runId"])
        self.assertEqual(result["baseline"]["provenance"]["kind"],vision_model.PROVIDER)
        self.assertEqual(sum(result[k] for k in ("fixed","regressed","bothCorrect","bothWrong")),2)
        with database.connect() as db:
            for run_id in (done["baselineRunId"],done["candidateRunId"]):
                losses = [r["train_loss"] for r in db.execute("SELECT train_loss,val_loss,accuracy FROM metrics WHERE run_id=? ORDER BY step",(run_id,)).fetchall()]
                self.assertEqual(len(losses),8); self.assertLess(losses[-1],losses[0])
                artifact = db.execute("SELECT * FROM artifacts WHERE run_id=?",(run_id,)).fetchone()
                saved = json.loads(self.store.get_bytes(artifact["object_key"]))
                self.assertEqual(saved["epoch"],8); self.assertIn("weights",saved)
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM evaluation_predictions WHERE evaluation_id=?",(result["candidate"]["id"],)).fetchone()["n"],2)
        for action in ("cancel","retry"):
            with self.assertRaises(ConflictError): self.experiments.action("default",job["id"],action)
        self.assertEqual(self.experiments.execute("default",job["id"],"expired"),{"experimentId":job["id"]})
        with self.assertRaises(NotFoundError): self.experiments.get("other",job["id"])
        self.assertEqual(self.experiments.list("default",Pagination(1,1))["pagination"]["total"],1)

    def test_leakage_invalid_labels_purpose_and_known_design_hashes_are_rejected(self):
        leaked = self.datasets.create_real("default",{"name":"overlap","purpose":"test","samples":samples(TRAIN[:1],"renamed")})
        with self.assertRaisesRegex(ValidationError,"overlap"): self.experiments.create("default",{**self.request,"testVersionId":leaked["id"]})
        unknown = self.datasets.create_real("default",{"name":"unknown","purpose":"test","samples":samples([("unknown",[100,100,100])])})
        with self.assertRaisesRegex(ValidationError,"labels"): self.experiments.create("default",{**self.request,"testVersionId":unknown["id"]})
        with self.assertRaises(ValidationError): self.experiments.create("default",{**self.request,"realTrainVersionId":self.test["id"]})
        source_id = self.synthetic["manifest"]["lineage"]["source"]["testSetId"]
        with database.connect() as db:
            db.execute("UPDATE evaluation_test_sets SET dataset_version_id=? WHERE id=?",(self.test["id"],source_id))
        with self.assertRaisesRegex(ValidationError,"design"): self.experiments.create("default",self.request)
        with database.connect() as db:
            db.execute("UPDATE evaluation_test_sets SET dataset_version_id=NULL WHERE id=?",(source_id,))
            db.execute("UPDATE evaluation_samples SET content_hash=? WHERE test_set_id=?",(self.test["manifest"]["samples"][0]["originalSha256"],source_id))
        with self.assertRaisesRegex(ValidationError,"design"): self.experiments.create("default",self.request)
        for values in ({"epochs":0},{"epochs":True},{"learningRate":float("inf")},{"regularization":-1},{"unknown":1}):
            with self.assertRaises(ValidationError): from_config(values)

    def test_cancellation_is_fenced_and_retry_resumes_the_actual_epoch(self):
        job = self.experiments.create("default",self.request); durable_queue.lease(job["taskId"],"old")
        actual, count = vision_model.step, []
        def cancel_after_second(*args):
            value = actual(*args); count.append(1)
            if len(count)==2: self.experiments.action("default",job["id"],"cancel")
            return value
        with patch.object(vision_model,"step",cancel_after_second), self.assertRaises(LeaseLost): self.experiments.execute("default",job["id"],"old")
        self.assertEqual(self.experiments.get("default",job["id"])["epochsCompleted"],1)
        self.experiments.action("default",job["id"],"retry"); durable_queue.lease(job["taskId"],"new")
        with self.assertRaises(LeaseLost): self.experiments.execute("default",job["id"],"old")
        with patch.object(vision_model,"step",wraps=actual) as step:
            self.experiments.execute("default",job["id"],"new"); self.assertEqual(step.call_count,15)
        self.assertEqual(self.experiments.get("default",job["id"])["epochsCompleted"],16)

    def test_bad_images_duplicate_pixels_and_changed_artifacts_fail_explicitly(self):
        bad = samples(TRAIN[:1])
        for data in ([],bad*2,[{**bad[0],"imageBase64":"not base64"}],[{**bad[0],"imageBase64":base64.b64encode(b"garbage").decode()}]):
            with self.assertRaises(ValidationError): self.datasets.create_real("default",{"name":"bad","purpose":"train","samples":data})
        with self.assertRaises(ValidationError): self.datasets.create_real("default",{"name":"bad","purpose":"train","samples":samples(TRAIN),"datasetId":self.test["datasetId"]})
        job = self.experiments.create("default",self.request); durable_queue.lease(job["taskId"],"cpu")
        info = self.real["manifest"]["samples"][0]["image"]
        self.store.put_bytes(info["key"],b"changed")
        with self.assertRaises(ConflictError): self.experiments.execute("default",job["id"],"cpu")
        self.assertEqual(self.experiments.get("default",job["id"])["epochsCompleted"],0)
        self.assertEqual(self.experiments.get("default",job["id"])["status"],"running")
        with patch.object(vision_model,"environment",return_value={}), self.assertRaises(ConflictError): self.experiments.execute("default",job["id"],"cpu")

def from_config(value):
    from vision_experiment_service import config
    return config(value)
