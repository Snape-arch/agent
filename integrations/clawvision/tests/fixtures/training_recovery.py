"""JSONL acceptance probe: pause after checkpoint 2 until its Worker is killed.

This tests orchestration and checkpoint transport, not model training quality.
"""
import argparse
import json
import time

parser = argparse.ArgumentParser()
parser.add_argument("--spec", required=True)
params = json.loads(parser.parse_args().spec)["params"]
checkpoint = params.get("_checkpoint") or {}
start = int(checkpoint.get("step", 0))
epochs = int(params.get("epochs", 6))
for step in range(start + 1, epochs + 1):
    print(json.dumps({"type": "metric", "step": step, "accuracy": .5 + step / 20, "trainLoss": 1 / step, "valLoss": 1.1 / step}), flush=True)
    print(json.dumps({"type": "checkpoint", "step": step, "content": {"step": step}}), flush=True)
    if not start and step == 2:
        time.sleep(120)
    time.sleep(.15)
print(json.dumps({"type": "artifact", "name": "recovered-confusion", "artifactType": "confusion-matrix", "step": epochs, "content": [[6, 0], [0, 6]]}), flush=True)
print(json.dumps({"type": "result", "status": "completed", "resumedFrom": start, "finalAccuracy": .5 + epochs / 20}), flush=True)
