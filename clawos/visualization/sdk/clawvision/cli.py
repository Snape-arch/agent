"""Command line entry point for synchronization and ecosystem migration."""

from __future__ import annotations

import argparse
import json

from . import _request, sync_offline
from .importers import export_mlflow, export_wandb, import_jsonl_history, import_mlflow, import_tensorboard, import_wandb


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="clawvision")
    root.add_argument("--url", help="ClawVision API base URL")
    root.add_argument("--token", help="API token (prefer CLAWVISION_API_TOKEN)")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="replay offline SDK batches")
    for name in ("tensorboard", "mlflow", "wandb", "jsonl"):
        command = commands.add_parser(f"import-{name}")
        command.add_argument("path")
        command.add_argument("--experiment", required=True)
        command.add_argument("--name")
    for name in ("mlflow", "wandb"):
        command = commands.add_parser(f"export-{name}")
        command.add_argument("run_id")
        command.add_argument("destination")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "sync":
        result = sync_offline()
    elif args.command == "import-tensorboard":
        result = {"runIds": import_tensorboard(args.path, args.experiment, base_url=args.url, api_token=args.token)}
    elif args.command == "import-mlflow":
        result = {"runId": import_mlflow(args.path, args.experiment, base_url=args.url, api_token=args.token)}
    elif args.command == "import-wandb":
        result = {"runId": import_wandb(args.path, args.experiment, base_url=args.url, api_token=args.token)}
    elif args.command == "import-jsonl":
        result = {"runId": import_jsonl_history(args.path, args.experiment, name=args.name, base_url=args.url, api_token=args.token)}
    else:
        if not args.url: raise SystemExit("--url is required for export commands")
        run = _request(args.url, f"/api/runs/{args.run_id}", method="GET", api_token=args.token)["data"]
        target = export_mlflow(run, args.destination) if args.command == "export-mlflow" else export_wandb(run, args.destination)
        result = {"path": str(target)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
