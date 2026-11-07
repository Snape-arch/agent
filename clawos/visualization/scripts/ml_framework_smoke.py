"""Real-package compatibility fixtures for supported ML integrations."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
# Lightning already installs PyTorch in this fixture environment. Reusing the
# torch backend keeps Keras native without adding TensorFlow/JAX solely for a
# callback contract check.
os.environ.setdefault("KERAS_BACKEND", "torch")


def check_tensorboard() -> dict:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    from tensorboard.compat.proto.event_pb2 import Event
    from tensorboard.compat.proto.summary_pb2 import Summary
    from tensorboard.summary.writer.event_file_writer import EventFileWriter
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        writer = EventFileWriter(directory)
        writer.add_event(Event(wall_time=1, step=3, summary=Summary(value=[Summary.Value(tag="loss", simple_value=.25)])))
        writer.flush(); writer.close()
        accumulator = EventAccumulator(directory); accumulator.Reload()
        event = accumulator.Scalars("loss")[0]
        return {"tag": "loss", "step": event.step, "value": event.value, "passed": event.step == 3 and abs(event.value - .25) < 1e-6}


def check_framework(name: str) -> dict:
    if name == "lightning":
        from lightning.pytorch.callbacks import Callback
        from clawvision.integrations import LightningCallback
        return {"class": LightningCallback.__name__, "passed": issubclass(LightningCallback, Callback)}
    if name == "transformers":
        from transformers import TrainerCallback
        from clawvision.integrations import HuggingFaceCallback
        return {"class": HuggingFaceCallback.__name__, "passed": issubclass(HuggingFaceCallback, TrainerCallback)}
    if name == "keras":
        from keras.callbacks import Callback
        from clawvision.integrations import KerasCallback
        return {"class": KerasCallback.__name__, "passed": issubclass(KerasCallback, Callback)}
    return check_tensorboard()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require", nargs="*", default=[])
    args = parser.parse_args()
    required = args.require or ["tensorboard", "lightning", "transformers", "keras"]
    results = {}
    for name in required:
        try:
            results[name] = check_framework(name)
        except Exception as error:
            results[name] = {"passed": False, "error": f"{type(error).__name__}: {error}"}
    passed = all(item["passed"] for item in results.values())
    print(json.dumps({"results": results, "passed": passed}, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
