"""Small real PyTorch trainer implementing ClawVision's JSONL worker protocol."""
from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import time


def emit(kind: str, **payload) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


def gpu_telemetry(torch) -> dict:
    if not torch.cuda.is_available(): return {"gpuUtilization":0,"gpuMemoryMb":0,"gpuTemperature":None}
    result={"gpuUtilization":None,"gpuMemoryMb":round(torch.cuda.memory_allocated()/1024/1024,2),"gpuTemperature":None}
    try:
        flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,"CREATE_NO_WINDOW") else 0
        raw=subprocess.check_output(["nvidia-smi","--query-gpu=utilization.gpu,memory.used,temperature.gpu","--format=csv,noheader,nounits","-i","0"],text=True,timeout=3,creationflags=flags).splitlines()[0]
        util,memory,temp=[float(value.strip()) for value in raw.split(",")[:3]];result.update(gpuUtilization=util,gpuMemoryMb=memory,gpuTemperature=temp)
    except Exception: pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec)
    params = spec.get("params", {})
    import torch

    seed = int(params.get("seed", 42)); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    device = torch.device("cuda" if torch.cuda.is_available() and spec.get("device", "auto") != "cpu" else "cpu")
    samples = max(128, min(4096, int(spec.get("samples", 768))))
    generator = torch.Generator().manual_seed(seed)
    x = torch.randn(samples, 12, generator=generator)
    weights = torch.randn(12, 3, generator=generator)
    y = (x @ weights + torch.randn(samples, 3, generator=generator) * .25).argmax(1)
    split = int(samples * .8); train_x, val_x = x[:split].to(device), x[split:].to(device)
    train_y, val_y = y[:split].to(device), y[split:].to(device)
    dropout = float(params.get("dropout", .2))
    model = torch.nn.Sequential(torch.nn.Linear(12, 32), torch.nn.ReLU(), torch.nn.Dropout(dropout), torch.nn.Linear(32, 3)).to(device)
    lr = float(params.get("learningRate", .001)); optimizer_name = str(params.get("optimizer", "AdamW"))
    optimizer_cls = {"SGD": torch.optim.SGD, "Adam": torch.optim.Adam}.get(optimizer_name, torch.optim.AdamW)
    optimizer = optimizer_cls(model.parameters(), lr=lr)
    epochs = max(1, min(100, int(params.get("epochs", 8)))); batch = max(4, min(split, int(params.get("batchSize", 64))))
    start_epoch = 0
    if params.get("_checkpoint"):
        checkpoint = torch.load(io.BytesIO(base64.b64decode(params["_checkpoint"])), map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["model"]); optimizer.load_state_dict(checkpoint["optimizer"]); start_epoch = int(checkpoint["epoch"])
        if "rngState" in checkpoint: torch.set_rng_state(checkpoint["rngState"].cpu())
        if device.type == "cuda" and checkpoint.get("cudaRngState"): torch.cuda.set_rng_state_all([state.cpu() for state in checkpoint["cudaRngState"]])
    emit("log", level="info", message=f"PyTorch {torch.__version__} · {device} · {torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'}")
    started = time.monotonic()
    for epoch in range(start_epoch + 1, epochs + 1):
        epoch_started=time.monotonic();model.train(); order = torch.randperm(split, device=device); total = 0.0
        try:
            for offset in range(0, split, batch):
                ids = order[offset:offset + batch]; optimizer.zero_grad(set_to_none=True)
                loss = torch.nn.functional.cross_entropy(model(train_x[ids]), train_y[ids]); loss.backward(); optimizer.step()
                total += float(loss.detach()) * len(ids)
        except torch.cuda.OutOfMemoryError:
            emit("telemetry",step=epoch,oom=True,**gpu_telemetry(torch));raise
        model.eval()
        with torch.no_grad():
            logits = model(val_x); val_loss = float(torch.nn.functional.cross_entropy(logits, val_y)); accuracy = float((logits.argmax(1) == val_y).float().mean())
        gpu = 0.0
        if device.type == "cuda": gpu = round(torch.cuda.max_memory_allocated() / 1024 / 1024, 2)
        emit("metric", step=epoch, trainLoss=total / split, valLoss=val_loss, accuracy=accuracy, learningRate=lr, gpu=gpu)
        emit("telemetry",step=epoch,samplesPerSecond=round(split/max(.001,time.monotonic()-epoch_started),2),oom=False,**gpu_telemetry(torch))
        buffer = io.BytesIO(); torch.save({"epoch": epoch, "model": model.state_dict(), "optimizer": optimizer.state_dict(), "rngState": torch.get_rng_state(), "cudaRngState": torch.cuda.get_rng_state_all() if device.type == "cuda" else []}, buffer)
        emit("checkpoint", step=epoch, content=base64.b64encode(buffer.getvalue()).decode())
    model.eval()
    with torch.no_grad():
        predictions = model(val_x).argmax(1).cpu(); truth = val_y.cpu(); matrix = torch.zeros(3, 3, dtype=torch.int64)
        for actual, predicted in zip(truth, predictions): matrix[actual, predicted] += 1
        accuracy = float((predictions == truth).float().mean())
    emit("artifact", name="confusion-matrix", artifactType="confusion-matrix", mimeType="application/json", step=epochs, content=matrix.tolist())
    emit("result", status="completed", device=str(device), durationMs=int((time.monotonic() - started) * 1000), finalAccuracy=accuracy)
    return 0


if __name__ == "__main__": raise SystemExit(main())
