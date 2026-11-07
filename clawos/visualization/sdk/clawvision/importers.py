"""Migration adapters for established ML experiment ecosystems."""

from __future__ import annotations

import json
import base64
import time
from pathlib import Path
from typing import Any

from . import Run, start_run


def import_tensorboard(
    log_dir: str | Path,
    experiment: str,
    *,
    base_url: str | None = None,
    api_token: str | None = None,
) -> list[str]:
    """Import scalar TensorBoard event files as one ClawVision run per event directory."""
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except ImportError as error:
        raise RuntimeError("TensorBoard import requires: pip install 'clawvision[tensorboard]'") from error
    root = Path(log_dir)
    event_dirs = sorted({path.parent for path in root.rglob("events.out.tfevents.*")})
    imported: list[str] = []
    for directory in event_dirs:
        accumulator = EventAccumulator(str(directory), size_guidance={"scalars": 0})
        accumulator.Reload()
        run = start_run(
            experiment,
            {"sourceLogDir": str(directory)},
            name=directory.name or experiment,
            base_url=base_url,
            api_token=api_token,
            lineage={"framework": "tensorboard", "dataset_ref": str(directory)},
        )
        points: dict[int, dict[str, float]] = {}
        for tag in accumulator.Tags().get("scalars", []):
            for event in accumulator.Scalars(tag):
                points.setdefault(int(event.step), {})[tag] = float(event.value)
        for step, metrics in sorted(points.items()):
            run.log_metrics(step, **metrics)
        run.finish(f"Imported {len(points)} TensorBoard steps")
        imported.append(run.id)
    return imported


def _metric_values(path: Path) -> list[tuple[int, float]]:
    if not path.is_file():
        return []
    rows = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return []
    values = []
    for row in rows:
        # MLflow file store metrics are: timestamp value step.
        values.append((int(row[2]) if len(row) > 2 else 0, float(row[1] if len(row) > 1 else row[0])))
    return values


def import_mlflow(
    run_directory: str | Path,
    experiment: str,
    *,
    base_url: str | None = None,
    api_token: str | None = None,
) -> str:
    """Import an MLflow file-store run without requiring the MLflow runtime."""
    source = Path(run_directory)
    if not source.is_dir():
        raise ValueError("MLflow run directory does not exist")
    params = {
        path.name: path.read_text(encoding="utf-8").strip()
        for path in (source / "params").glob("*")
        if path.is_file()
    }
    tags = {path.name: path.read_text(encoding="utf-8").strip() for path in (source / "tags").glob("*") if path.is_file()}
    if tags: params["_mlflowTags"] = tags
    run = start_run(
        experiment,
        params,
        name=source.name,
        base_url=base_url,
        api_token=api_token,
        lineage={"framework": "mlflow", "dataset_ref": str(source)},
    )
    points: dict[int, dict[str, float]] = {}
    for path in (source / "metrics").glob("*"):
        for step, metric in _metric_values(path):
            points.setdefault(step, {})[path.name] = metric
    for step, metrics in sorted(points.items()):
        run.log_metrics(step, **metrics)
    for path in (source / "artifacts").rglob("*"):
        if path.is_file() and path.stat().st_size <= 10 * 1024 * 1024:
            run.log_artifact(
                str(path.relative_to(source / "artifacts")),
                {"base64": base64.b64encode(path.read_bytes()).decode(), "filename": path.name},
                "file",
                mime_type="application/octet-stream",
            )
    run.finish(f"Imported MLflow run with {len(points)} metric steps")
    return run.id


def import_wandb(
    run_directory: str | Path,
    experiment: str,
    *,
    base_url: str | None = None,
    api_token: str | None = None,
) -> str:
    """Import an offline W&B run directory including config, history and files."""
    source = Path(run_directory)
    files = source / "files" if (source / "files").is_dir() else source
    histories = sorted(set(files.glob("wandb-history*.jsonl")) | set(source.glob("wandb-history*.jsonl")))
    native_logs = sorted(source.rglob("run-*.wandb"))
    if not histories and not native_logs:
        raise ValueError("W&B run directory has no wandb-history JSONL file")
    config: dict[str, Any] = {}
    for candidate in (files / "config.json", files / "config.yaml", source / "config.json", source / "config.yaml"):
        if not candidate.is_file(): continue
        text = candidate.read_text(encoding="utf-8")
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict): config = {key: value.get("value") if isinstance(value, dict) and "value" in value else value for key, value in loaded.items()}
        except json.JSONDecodeError:
            key = None
            for line in text.splitlines():
                if line and not line.startswith(" ") and line.rstrip().endswith(":"): key = line.rstrip()[:-1]
                elif key and line.strip().startswith("value:"): config[key] = line.split(":", 1)[1].strip().strip("'\"")
        break
    native_points: dict[int, dict[str, float]] = {}
    for native_log in native_logs:
        try:
            from wandb.proto import wandb_internal_pb2
            from wandb.sdk.internal.datastore import DataStore
        except ImportError as error:
            raise RuntimeError("native .wandb import requires: pip install wandb") from error
        store = DataStore(); store.open_for_scan(str(native_log))
        while True:
            try: payload = store.scan_data()
            except EOFError: break
            if not payload: break
            record = wandb_internal_pb2.Record(); record.ParseFromString(payload)
            if record.HasField("config"):
                for item in record.config.update:
                    if item.key and item.value_json: config[item.key] = json.loads(item.value_json)
            if record.HasField("history"):
                values = {item.key: json.loads(item.value_json) for item in record.history.item if item.key and item.value_json}
                step = int(record.history.step.num if record.history.HasField("step") else values.get("_step", len(native_points)))
                native_points.setdefault(step, {}).update({key: float(value) for key, value in values.items() if isinstance(value, (int, float)) and not key.startswith("_")})
    run = start_run(experiment, config, name=source.name, base_url=base_url, api_token=api_token,
                    lineage={"framework": "wandb", "dataset_ref": str(source)})
    points: dict[int, dict[str, float]] = native_points
    for history in histories:
        for index, line in enumerate(history.read_text(encoding="utf-8").splitlines()):
            if not line.strip(): continue
            item = json.loads(line); step = int(item.get("_step", index))
            numeric = {key: float(value) for key, value in item.items() if isinstance(value, (int, float)) and not key.startswith("_")}
            points.setdefault(step, {}).update(numeric)
    for step, metrics in sorted(points.items()): run.log_metrics(step, **metrics)
    for artifact in files.rglob("*"):
        if artifact.is_file() and artifact not in histories and artifact not in native_logs and artifact.name not in {"config.json", "config.yaml", "wandb-summary.json"} and artifact.stat().st_size <= 10 * 1024 * 1024:
            run.log_artifact(str(artifact.relative_to(files)), {"base64": base64.b64encode(artifact.read_bytes()).decode(), "filename": artifact.name}, "file", mime_type="application/octet-stream")
    run.finish(f"Imported W&B run with {len(points)} metric steps")
    return run.id


def _write_artifacts(run: dict[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, artifact in enumerate(run.get("artifacts") or []):
        name = str(artifact.get("name") or f"artifact-{index}.json").replace("..", "_")
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = artifact.get("content")
        if isinstance(content, dict) and content.get("base64"):
            target.write_bytes(base64.b64decode(content["base64"]))
        else:
            target.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def export_mlflow(run: dict[str, Any], destination: str | Path) -> Path:
    """Export a ClawVision run into an importable MLflow file-store run."""
    root = Path(destination) / str(run["id"])
    for folder in ("params", "metrics", "artifacts", "tags"): (root / folder).mkdir(parents=True, exist_ok=True)
    for key, value in (run.get("params") or {}).items(): (root / "params" / str(key)).write_text(str(value), encoding="utf-8")
    timestamp = int(time.time() * 1000)
    aliases = {"trainLoss": "loss", "valLoss": "val_loss", "learningRate": "learning_rate"}
    by_metric: dict[str, list[str]] = {}
    for point in run.get("metrics") or []:
        step = int(point.get("step", 0))
        for key, value in point.items():
            if key != "step" and value is not None: by_metric.setdefault(aliases.get(key, key), []).append(f"{timestamp} {float(value)} {step}")
    for key, rows in by_metric.items(): (root / "metrics" / key).write_text("\n".join(rows) + "\n", encoding="utf-8")
    (root / "tags" / "mlflow.runName").write_text(str(run.get("name") or run["id"]), encoding="utf-8")
    (root / "meta.yaml").write_text(f"run_id: {run['id']}\nrun_name: {run.get('name') or run['id']}\nstatus: 3\n", encoding="utf-8")
    _write_artifacts(run, root / "artifacts")
    return root


def export_wandb(run: dict[str, Any], destination: str | Path) -> Path:
    """Export a ClawVision run into W&B offline-run compatible files."""
    root = Path(destination) / f"offline-run-{run['id']}" / "files"; root.mkdir(parents=True, exist_ok=True)
    config = {key: {"value": value} for key, value in (run.get("params") or {}).items()}
    (root / "config.yaml").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    history = []
    for point in run.get("metrics") or []: history.append(json.dumps({"_step": int(point.get("step", 0)), **{key: value for key, value in point.items() if key != "step" and value is not None}}, ensure_ascii=False))
    (root / "wandb-history.jsonl").write_text("\n".join(history) + ("\n" if history else ""), encoding="utf-8")
    summary = {key: value for point in run.get("metrics") or [] for key, value in point.items() if key != "step" and value is not None}
    (root / "wandb-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_artifacts(run, root / "artifacts")
    return root.parent


def import_jsonl_history(
    history_file: str | Path,
    experiment: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_token: str | None = None,
) -> str:
    """Import W&B-style JSONL history or another line-delimited metric log."""
    source = Path(history_file)
    run: Run = start_run(
        experiment,
        {"sourceHistory": str(source)},
        name=name or source.stem,
        base_url=base_url,
        api_token=api_token,
        lineage={"framework": "jsonl-history", "dataset_ref": str(source)},
    )
    count = 0
    for index, line in enumerate(source.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        item: dict[str, Any] = json.loads(line)
        step = int(item.pop("_step", item.pop("step", index)))
        metrics = {
            key: float(value)
            for key, value in item.items()
            if isinstance(value, (int, float)) and not key.startswith("_")
        }
        if metrics:
            run.log_metrics(step, **metrics)
            count += 1
    run.finish(f"Imported {count} JSONL metric steps")
    return run.id
