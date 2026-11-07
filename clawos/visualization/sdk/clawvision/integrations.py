"""Callbacks for common training frameworks with optional native base classes."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from numbers import Number
from typing import Any

from . import Run, start_run

try:
    from lightning.pytorch.callbacks import Callback as _LightningBase
except ImportError:
    class _LightningBase:  # type: ignore[no-redef]
        pass

try:
    from transformers import TrainerCallback as _TransformersBase
except ImportError:
    class _TransformersBase:  # type: ignore[no-redef]
        pass

try:
    from keras.callbacks import Callback as _KerasBase
except ImportError:
    class _KerasBase:  # type: ignore[no-redef]
        pass


def environment_snapshot() -> dict[str, Any]:
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "cudaVisibleDevices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "condaEnv": os.environ.get("CONDA_DEFAULT_ENV")}


class TrainingCallback:
    """Framework-neutral callback and context manager."""
    def __init__(self, experiment: str, params: dict[str, Any] | None = None, *, framework: str = "custom",
                 code_ref: str | None = None, dataset_ref: str | None = None,
                 base_url: str | None = None, api_token: str | None = None, rank: int | None = None,
                 world_size: int | None = None, state_path: str | Path | None = None,
                 parent_run_id: str | None = None, resume_checkpoint_key: str | None = None):
        super().__init__()
        self.rank = int(os.environ.get("RANK", "0")) if rank is None else rank
        self.world_size = int(os.environ.get("WORLD_SIZE", "1")) if world_size is None else world_size
        self.state_path = Path(state_path) if state_path else None
        self._seen: set[str] = set()
        self._closed = False
        self.run: Run | None = None
        state = self._load_state()
        self._seen.update(str(item) for item in state.get("seen", []))
        if self.rank == 0:
            if state.get("runId"):
                self.run = Run(str(state["runId"]), base_url or os.environ.get("CLAWVISION_URL", "http://127.0.0.1:8787"), api_token=api_token)
                self.run.resume(resume_checkpoint_key or state.get("checkpoint"))
                self.run.log_lineage(framework=framework, code_ref=code_ref, dataset_ref=dataset_ref,
                                     environment=environment_snapshot(), parent_run_id=parent_run_id,
                                     resume_checkpoint_key=resume_checkpoint_key or state.get("checkpoint"),
                                     world_size=self.world_size, rank_count=self.world_size)
            else:
                self.run = start_run(experiment, params, base_url=base_url, api_token=api_token,
                                     lineage={"framework": framework, "code_ref": code_ref, "dataset_ref": dataset_ref,
                                              "environment": environment_snapshot(), "parent_run_id": parent_run_id,
                                              "resume_checkpoint_key": resume_checkpoint_key,
                                              "world_size": self.world_size, "rank_count": self.world_size})
            self._persist_state(status="running", checkpoint=resume_checkpoint_key or state.get("checkpoint"))

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path or not self.state_path.is_file():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _persist_state(self, **updates: Any) -> None:
        if not self.state_path or self.rank != 0:
            return
        state = {**self._load_state(), **updates, "runId": self.run.id if self.run else None, "seen": sorted(self._seen)}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def metrics(self, step: int, values: dict[str, Any]) -> None:
        if not self.run: return
        numeric = {}
        for key, value in values.items():
            candidate = value.item() if callable(getattr(value, "item", None)) else value
            if isinstance(candidate, Number): numeric[str(key)] = float(candidate)
        fingerprint = hashlib.sha256(json.dumps([int(step), sorted(numeric.items())], separators=(",", ":")).encode()).hexdigest()
        if numeric and fingerprint not in self._seen:
            self._seen.add(fingerprint); self.run.log_metrics(step, **numeric); self._persist_state()

    def checkpoint(self, path: str | Path, step: int) -> None:
        source = Path(path)
        fingerprint = f"checkpoint:{step}:{source.resolve()}:{source.stat().st_size}" if source.is_file() else ""
        if self.run and fingerprint and fingerprint not in self._seen:
            self._seen.add(fingerprint); self.run.log_checkpoint(source, step); self._persist_state(checkpoint=str(source))

    def close(self, error: BaseException | None = None) -> None:
        if self.run and not self._closed:
            self.run.fail(str(error)) if error else self.run.finish()
            self._closed = True
            self._persist_state(status="failed" if error else "completed", error=str(error) if error else None)

    def __enter__(self): return self
    def __exit__(self, exc_type, exc, traceback): self.close(exc); return False


class LightningCallback(TrainingCallback, _LightningBase):
    """Compatible with ``lightning.pytorch.Callback`` hook names."""
    def on_train_epoch_end(self, trainer, pl_module) -> None:
        metrics = {str(key): getattr(value, "item", lambda: value)() for key, value in getattr(trainer, "callback_metrics", {}).items()}
        self.metrics(int(getattr(trainer, "global_step", 0)), metrics)

    def on_save_checkpoint(self, trainer, pl_module, checkpoint) -> None:
        path = getattr(getattr(trainer, "checkpoint_callback", None), "last_model_path", "")
        if path: self.checkpoint(path, int(getattr(trainer, "global_step", 0)))

    def on_train_end(self, trainer, pl_module) -> None: self.close()
    def on_exception(self, trainer, pl_module, exception) -> None: self.close(exception)


class HuggingFaceCallback(TrainingCallback, _TransformersBase):
    """Compatible with ``transformers.TrainerCallback`` hook names."""
    def on_log(self, args, state, control, logs=None, **kwargs):
        self.metrics(int(getattr(state, "global_step", 0)), logs or {}); return control

    def on_save(self, args, state, control, **kwargs):
        checkpoint = Path(getattr(args, "output_dir", ".")) / f"checkpoint-{getattr(state, 'global_step', 0)}"
        candidates = list(checkpoint.glob("*.safetensors")) + list(checkpoint.glob("*.bin")) if checkpoint.exists() else []
        if candidates: self.checkpoint(candidates[0], int(getattr(state, "global_step", 0)))
        return control

    def on_train_end(self, args, state, control, **kwargs): self.close(); return control


class KerasCallback(TrainingCallback, _KerasBase):
    """Compatible with ``tf.keras.callbacks.Callback`` methods without importing TensorFlow."""
    model: Any = None
    def set_model(self, model) -> None: self.model = model
    def on_epoch_end(self, epoch, logs=None) -> None: self.metrics(int(epoch) + 1, logs or {})
    def on_train_end(self, logs=None) -> None: self.close()
