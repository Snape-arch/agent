# ML Ecosystem Integration

ClawVision 0.21 validates framework behavior with real training loops rather
than callback inheritance alone.

## Training integrations

- Lightning runs a real `Trainer.fit()` for two epochs and writes a native
  `.ckpt` checkpoint.
- Hugging Face Trainer trains to step 3, saves a complete checkpoint, then a
  new Trainer restores optimizer, scheduler, RNG and model state and continues
  to step 5.
- Keras runs `model.fit()` for three epochs with the Torch backend.
- PyTorch DDP launches two Gloo processes and verifies that only global rank 0
  creates and reports the ClawVision Run.

Callbacks accept `state_path`. Rank 0 atomically records the Run ID, emitted
metric fingerprints, last checkpoint and terminal state. A replacement process
loads that state, resumes the same Run and suppresses exact metric/checkpoint
replays. `RANK` and `WORLD_SIZE` are detected from the distributed environment
unless explicitly supplied.

The API additionally stores `(run_id,event_id)` ingestion receipts. Replayed
batches do not duplicate events, metrics merge non-null fields at an existing
step, and artifacts use deterministic retry-safe identities. Migration v16
adds the receipt table for both SQLite and PostgreSQL.

## MLflow and W&B migration

The CLI supports both directions:

```bash
clawvision --url http://127.0.0.1:8787 import-mlflow ./mlruns/... --experiment migrated
clawvision --url http://127.0.0.1:8787 import-wandb ./wandb/offline-run-... --experiment migrated
clawvision --url http://127.0.0.1:8787 export-mlflow RUN_ID ./exports
clawvision --url http://127.0.0.1:8787 export-wandb RUN_ID ./exports
```

MLflow import preserves all metric steps, parameters, tags and binary
artifacts. W&B import accepts JSONL history and the native offline `.wandb`
record stream, including config and history records. Exporters produce MLflow
file-store and W&B offline-run layouts that ClawVision can import again.

## Reproducible acceptance

Install the isolated dependencies and run:

```bash
pip install -r requirements-ml-test.txt
python scripts/ml_ecosystem_acceptance.py \
  --output docs/benchmarks/ml-ecosystem.json
```

The scheduled CI job repeats the suite on Linux and uploads its evidence. The
committed Windows report records framework steps, checkpoint recovery, DDP
world size, failure recovery, de-duplicated steps and migration round trips.
