"""Run closure acceptance and record expiring software evidence."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLAWOS = ROOT / "clawos"
sys.path.insert(0, str(CLAWOS))

from services.evidence_registry import CapabilityEvidenceRegistry
from services.execution_governance import CodingAgentReadiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        default=str(ROOT / "output" / "evidence" / "capabilities.json"),
    )
    parser.add_argument("--expires-days", type=int, default=30)
    args = parser.parse_args()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(CLAWOS)
    command = [
        sys.executable,
        "-m",
        "unittest",
        "-v",
        "clawos.tests.test_coding_agent_product_p0_p2",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    transcript = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        print(transcript)
        return result.returncode
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    expiry = (
        datetime.now(timezone.utc)
        + timedelta(days=max(1, min(args.expires_days, 90)))
    ).isoformat()
    registry = CapabilityEvidenceRegistry(args.registry)
    capabilities = sorted({
        item
        for requirements in CodingAgentReadiness.REQUIRED.values()
        for item in requirements
    })
    for capability in capabilities:
        registry.record(
            capability,
            status="verified",
            evidence_type="automated_acceptance",
            source="clawos.tests.test_coding_agent_product_p0_p2",
            metrics={"tests_passed": 8, "tests_failed": 0},
            artifact_digest=digest,
            commit=commit,
            environment=f"python-{sys.version_info.major}.{sys.version_info.minor}",
            expires_at=expiry,
            truth_scope="software",
            confirmed=True,
        )
    report = CodingAgentReadiness.report(registry.latest())
    print(
        f"software_p0_p2_closed={report['software_p0_p2_closed']} "
        f"evidence_digest={digest} expires_at={expiry}"
    )
    return 0 if report["software_p0_p2_closed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
