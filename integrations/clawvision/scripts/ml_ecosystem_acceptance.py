"""Run real training loops and migration round trips for supported ML ecosystems."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
os.environ.setdefault("KERAS_BACKEND", "torch")


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.RLock(); self.runs: dict[str, dict] = {}; self.receipts: set[tuple[str, str]] = set()

    def apply(self, path: str, payload: dict) -> dict:
        with self.lock:
            parts = path.strip("/").split("/")
            if path == "/api/runs":
                self.runs[payload["id"]] = {**payload, "status": "running", "metrics": {}, "events": [], "artifacts": [], "lineage": {}}
                return {"data": self.runs[payload["id"]]}
            run_id, action = parts[2], parts[3]
            run = self.runs[run_id]
            if action == "batch":
                for kind in ("metrics", "events", "artifacts"):
                    for item in payload.get(kind, []):
                        event_id = str(item.get("eventId") or "")
                        if event_id and (run_id, event_id) in self.receipts: continue
                        if event_id: self.receipts.add((run_id, event_id))
                        if kind == "metrics":
                            step = int(item["step"]); run["metrics"].setdefault(step, {}).update({key: value for key, value in item.items() if key not in {"step", "eventId"}})
                        else: run[kind].append(item)
                return {"ok": True}
            if action == "lineage": run["lineage"].update(payload)
            elif action == "resume": run["status"] = "running"; run["resumes"] = int(run.get("resumes", 0)) + 1
            elif action == "finish": run["status"] = "completed"
            elif action == "fail": run["status"] = "failed"
            return {"data": run}


class Handler(BaseHTTPRequestHandler):
    recorder: Recorder
    def log_message(self, *_args) -> None: pass
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length) or b"{}")
        response = json.dumps(self.recorder.apply(self.path, payload)).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(response))); self.end_headers(); self.wfile.write(response)


def recorder_server() -> tuple[ThreadingHTTPServer, threading.Thread, Recorder, str]:
    recorder = Recorder(); handler = type("AcceptanceHandler", (Handler,), {"recorder": recorder})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    return server, thread, recorder, f"http://127.0.0.1:{server.server_port}"


def lightning_fixture(base_url: str, root: Path) -> dict:
    import torch
    from lightning import LightningModule, Trainer
    from lightning.pytorch.callbacks import ModelCheckpoint
    from torch.utils.data import DataLoader, TensorDataset
    from clawvision import LightningCallback

    class Model(LightningModule):
        def __init__(self): super().__init__(); self.layer = torch.nn.Linear(4, 2)
        def training_step(self, batch, _index):
            x, y = batch; loss = torch.nn.functional.cross_entropy(self.layer(x), y); self.log("train_loss", loss, on_epoch=True); return loss
        def configure_optimizers(self): return torch.optim.SGD(self.parameters(), lr=.1)

    torch.manual_seed(7); loader = DataLoader(TensorDataset(torch.randn(16, 4), torch.arange(16) % 2), batch_size=4)
    checkpoint = ModelCheckpoint(dirpath=root / "lightning", save_last=True, every_n_epochs=1)
    callback = LightningCallback("lightning-real", {"epochs": 2}, framework="lightning", base_url=base_url, state_path=root / "lightning-state.json")
    trainer = Trainer(max_epochs=2, accelerator="cpu", devices=1, logger=False, enable_progress_bar=False, enable_model_summary=False, callbacks=[checkpoint, callback])
    trainer.fit(Model(), train_dataloaders=loader)
    return {"epochs": trainer.current_epoch, "globalStep": trainer.global_step, "checkpoint": Path(checkpoint.last_model_path).is_file(), "passed": trainer.global_step == 8 and Path(checkpoint.last_model_path).is_file()}


def transformers_fixture(base_url: str, root: Path) -> dict:
    import torch
    from transformers import Trainer, TrainingArguments
    from clawvision import HuggingFaceCallback

    class Dataset(torch.utils.data.Dataset):
        def __init__(self): self.x = torch.arange(48, dtype=torch.float32).reshape(12, 4) / 48; self.y = torch.arange(12) % 2
        def __len__(self): return len(self.y)
        def __getitem__(self, index): return {"input_ids": self.x[index], "labels": self.y[index]}

    class Model(torch.nn.Module):
        def __init__(self): super().__init__(); self.layer = torch.nn.Linear(4, 2)
        def forward(self, input_ids=None, labels=None):
            logits = self.layer(input_ids); return {"loss": torch.nn.functional.cross_entropy(logits, labels), "logits": logits}

    output = root / "transformers"; state = root / "transformers-state.json"
    first_args = TrainingArguments(str(output), max_steps=3, per_device_train_batch_size=2, logging_steps=1, save_steps=3, save_strategy="steps", report_to=[], disable_tqdm=True)
    first = Trainer(model=Model(), args=first_args, train_dataset=Dataset(), callbacks=[HuggingFaceCallback("hf-real", framework="transformers", base_url=base_url, state_path=state)])
    first.train(); checkpoint = output / "checkpoint-3"
    second_args = TrainingArguments(str(output), max_steps=5, per_device_train_batch_size=2, logging_steps=1, save_steps=5, save_strategy="steps", report_to=[], disable_tqdm=True)
    second = Trainer(model=Model(), args=second_args, train_dataset=Dataset(), callbacks=[HuggingFaceCallback("hf-real", framework="transformers", base_url=base_url, state_path=state, resume_checkpoint_key=str(checkpoint))])
    result = second.train(resume_from_checkpoint=str(checkpoint))
    return {"firstStep": first.state.global_step, "resumedStep": second.state.global_step, "checkpoint": checkpoint.is_dir(), "loss": result.training_loss, "passed": first.state.global_step == 3 and second.state.global_step == 5 and checkpoint.is_dir()}


def keras_fixture(base_url: str, root: Path) -> dict:
    import numpy as np
    import keras
    from clawvision import KerasCallback
    rng = np.random.default_rng(11); x = rng.normal(size=(32, 4)).astype("float32"); y = (x.sum(axis=1) > 0).astype("int32")
    model = keras.Sequential([keras.layers.Input((4,)), keras.layers.Dense(8, activation="relu"), keras.layers.Dense(2, activation="softmax")])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    history = model.fit(x, y, epochs=3, batch_size=8, verbose=0, callbacks=[KerasCallback("keras-real", framework="keras", base_url=base_url, state_path=root / "keras-state.json")])
    return {"epochs": len(history.history["loss"]), "finalLoss": float(history.history["loss"][-1]), "passed": len(history.history["loss"]) == 3}


def _ddp_worker(rank: int, world_size: int, init_method: str, base_url: str, state_path: str) -> None:
    import torch
    import torch.distributed as dist
    from clawvision import TrainingCallback
    os.environ["RANK"] = str(rank); os.environ["WORLD_SIZE"] = str(world_size)
    dist.init_process_group("gloo", init_method=init_method, rank=rank, world_size=world_size)
    model = torch.nn.parallel.DistributedDataParallel(torch.nn.Linear(4, 1)); optimizer = torch.optim.SGD(model.parameters(), lr=.1)
    x = torch.ones(4, 4) * (rank + 1); loss = model(x).pow(2).mean(); loss.backward(); optimizer.step()
    callback = TrainingCallback("ddp-real", framework="pytorch", base_url=base_url, state_path=state_path)
    callback.metrics(1, {"loss": float(loss.detach())}); callback.close(); dist.barrier(); dist.destroy_process_group()


def ddp_fixture(base_url: str, root: Path, recorder: Recorder) -> dict:
    import torch.multiprocessing as mp
    with socket.socket() as sock: sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    mp.spawn(_ddp_worker, args=(2, f"tcp://127.0.0.1:{port}", base_url, str(root / "ddp-state.json")), nprocs=2, join=True)
    state = json.loads((root / "ddp-state.json").read_text(encoding="utf-8"))
    run = recorder.runs[state["runId"]]
    return {"worldSize": 2, "runId": state["runId"], "reportedRuns": 1, "metricSteps": sorted(run["metrics"]),
            "passed": bool(state["runId"]) and run["lineage"].get("worldSize") == 2 and sorted(run["metrics"]) == [1]}


def recovery_fixture(base_url: str, root: Path, recorder: Recorder) -> dict:
    from clawvision import TrainingCallback
    state = root / "recovery-state.json"
    first = TrainingCallback("recover", framework="pytorch", base_url=base_url, state_path=state)
    first.metrics(1, {"loss": 1.0}); first.metrics(1, {"loss": 1.0}); first.run.flush(); first.close(RuntimeError("rank 1 disconnected"))
    second = TrainingCallback("recover", framework="pytorch", base_url=base_url, state_path=state, resume_checkpoint_key="checkpoint-1")
    second.metrics(1, {"loss": 1.0}); second.metrics(2, {"loss": .5}); second.close()
    run = recorder.runs[second.run.id]
    return {"runId": second.run.id, "resumes": run.get("resumes", 0), "steps": sorted(run["metrics"]), "status": run["status"], "passed": sorted(run["metrics"]) == [1, 2] and run["status"] == "completed"}


def migration_fixture(base_url: str, root: Path) -> dict:
    import mlflow
    import wandb
    from clawvision.importers import export_mlflow, export_wandb, import_mlflow, import_wandb
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    tracking = root / "mlruns"; mlflow.set_tracking_uri(tracking.as_uri()); mlflow.set_experiment("acceptance")
    artifact = root / "native.txt"; artifact.write_text("native", encoding="utf-8")
    with mlflow.start_run(run_name="native") as active:
        mlflow.log_param("lr", .01); mlflow.log_metric("loss", 1.0, step=0); mlflow.log_metric("loss", .5, step=1); mlflow.log_artifact(str(artifact))
        mlflow_id = active.info.run_id
    mlflow_dir = next(path for path in tracking.rglob(mlflow_id) if (path / "metrics").is_dir())
    imported_mlflow = import_mlflow(mlflow_dir, "mlflow-native", base_url=base_url)
    os.environ["WANDB_SILENT"] = "true"; os.environ["WANDB_DIR"] = str(root); os.environ["WANDB_CACHE_DIR"] = str(root / "wandb-cache"); os.environ["WANDB_CONFIG_DIR"] = str(root / "wandb-config")
    native_wandb = wandb.init(project="clawvision-acceptance", name="native", dir=str(root), mode="offline", reinit="finish_previous")
    native_wandb.config.update({"lr": .02}); native_wandb.log({"loss": 1.0}, step=0); native_wandb.log({"loss": .4}, step=1); native_wandb.finish()
    wandb_dir = Path(native_wandb.dir).parent
    imported_wandb = import_wandb(wandb_dir, "wandb-native", base_url=base_url)
    sample = {"id": "roundtrip", "name": "roundtrip", "params": {"lr": .1}, "metrics": [{"step": 0, "trainLoss": 1.0}, {"step": 1, "trainLoss": .2}], "artifacts": []}
    mlflow_export = export_mlflow(sample, root / "exports-mlflow"); wandb_export = export_wandb(sample, root / "exports-wandb")
    roundtrip_mlflow = import_mlflow(mlflow_export, "roundtrip-mlflow", base_url=base_url); roundtrip_wandb = import_wandb(wandb_export, "roundtrip-wandb", base_url=base_url)
    return {"nativeMlflow": imported_mlflow, "nativeWandb": imported_wandb, "roundtripMlflow": roundtrip_mlflow, "roundtripWandb": roundtrip_wandb, "passed": all((imported_mlflow, imported_wandb, roundtrip_mlflow, roundtrip_wandb))}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output"); parser.add_argument("--skip-migrations", action="store_true"); parser.add_argument("--only-migrations", action="store_true"); args = parser.parse_args()
    server, thread, recorder, base_url = recorder_server()
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            results = {} if args.only_migrations else {
                "lightning": lightning_fixture(base_url, root), "transformers": transformers_fixture(base_url, root),
                "keras": keras_fixture(base_url, root), "ddp": ddp_fixture(base_url, root, recorder), "recovery": recovery_fixture(base_url, root, recorder),
            }
            if not args.skip_migrations: results["migration"] = migration_fixture(base_url, root)
            report = {"schemaVersion": 1, "results": results, "runs": len(recorder.runs), "passed": all(item["passed"] for item in results.values())}
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            if args.output: target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(encoded + "\n", encoding="utf-8")
            print(encoded); raise SystemExit(0 if report["passed"] else 1)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__": main()
