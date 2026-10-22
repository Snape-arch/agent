#!/usr/bin/env python3
"""Emit the unified product-readiness report without inflating external evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CLAWOS = Path(__file__).resolve().parents[1]
ROOT = CLAWOS.parent
sys.path.insert(0, str(CLAWOS))

from agent_learning import AdvancedLearningReadiness
from memoryos.memory_store import MemoryStore
from services.product_readiness_service import ProductReadinessService


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default=str(ROOT / "output"))
    parser.add_argument("--database", default=str(CLAWOS / "memoryos.db"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    store = MemoryStore(str(Path(args.database).expanduser().resolve()))
    report = ProductReadinessService(root).report(
        learning=AdvancedLearningReadiness(store).report(),
        evaluator=load_json(output / "coding-evaluator" / "summary.json"),
        outcome_benchmark=load_json(
            output / "coding-benchmark" / "latest.json"
        ),
        hardware=load_json(
            output / "competition_hardware_acceptance.json"
        ),
        ide_artifact=load_json(
            output / "evidence" / "vscode-extension.json"
        ),
        sandbox_artifact=load_json(
            output / "evidence" / "os-sandbox.json"
        ),
        restricted_token_artifact=load_json(
            output / "evidence" / "restricted-token.json"
        ),
        egress_proxy_artifact=load_json(
            output / "evidence" / "egress-proxy.json"
        ),
        recovery_artifact=load_json(
            output / "evidence" / "task-recovery.json"
        ),
        recovery_soak_artifact=load_json(
            output / "evidence" / "multi-worker-recovery-soak.json"
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if (report["product_ready"] or not args.strict) else 2


if __name__ == "__main__":
    raise SystemExit(main())
