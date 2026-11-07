"""Enforce the overall and risk-focused Python coverage release gates."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


OVERALL_MINIMUM = 60.0
MODULE_MINIMUMS = {
    "backend/asgi.py": 80.0,
    "backend/database.py": 55.0,
    "backend/durable_queue.py": 75.0,
    "backend/security.py": 75.0,
    "backend/run_service.py": 85.0,
    "backend/evaluation_service.py": 85.0,
    "backend/scenario_service.py": 85.0,
    "backend/synthesis_service.py": 85.0,
    "backend/synthetic_renderer.py": 85.0,
    "backend/vision_model.py": 85.0,
    "backend/vision_dataset_service.py": 85.0,
    "backend/vision_experiment_service.py": 85.0,
    "sdk/clawvision/evaluation.py": 75.0,
    "sdk/clawvision/__init__.py": 45.0,
}


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "coverage.json"
        result = subprocess.run(
            [sys.executable, "-m", "coverage", "json", "-o", str(output)],
            check=False,
        )
        if result.returncode:
            return result.returncode
        report = json.loads(output.read_text(encoding="utf-8"))

    failures: list[str] = []
    total = float(report["totals"]["percent_covered"])
    if total < OVERALL_MINIMUM:
        failures.append(f"overall: {total:.1f}% < {OVERALL_MINIMUM:.1f}%")
    files = {name.replace("\\", "/"): value for name, value in report["files"].items()}
    for name, minimum in MODULE_MINIMUMS.items():
        covered = float(files.get(name, {}).get("summary", {}).get("percent_covered", 0))
        if covered < minimum:
            failures.append(f"{name}: {covered:.1f}% < {minimum:.1f}%")
        else:
            print(f"coverage gate {name}: {covered:.1f}% >= {minimum:.1f}%")
    print(f"coverage gate overall: {total:.1f}% >= {OVERALL_MINIMUM:.1f}%")
    if failures:
        print("Coverage gate failed:\n- " + "\n- ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
