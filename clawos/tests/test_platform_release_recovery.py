from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.package_vscode_extension import development_identity
from services.os_sandbox import WindowsJobSandbox
from services.product_readiness_service import ProductReadinessService
from services.vsix_release import VsixReleaseService


class PlatformReleaseRecoveryTests(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Windows", "Windows Job Object probe")
    def test_windows_job_backend_is_really_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = WindowsJobSandbox(
                max_processes=1, process_memory_mb=128
            ).run_probe(tmp)
        self.assertTrue(report["passed"])
        self.assertTrue(report["os_enforced"])
        self.assertTrue(
            report["resource_isolation"]["nested_process_blocked"]
        )
        self.assertFalse(report["filesystem_isolated"])
        self.assertFalse(report["network_isolated"])
        self.assertFalse(report["production_sandbox_ready"])

    def test_vsix_is_reproducible_signed_and_tamper_evident(self):
        service = VsixReleaseService(ROOT / "integrations" / "vscode")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = service.package(directory / "first.vsix")
            second = service.package(directory / "second.vsix")
            key, certificate = development_identity()
            signature = service.sign(
                directory / "first.vsix", key, certificate,
                directory / "first.vsix.sig.json",
            )
            verified = service.verify_signature(
                directory / "first.vsix",
                directory / "first.vsix.sig.json",
            )
            with (directory / "first.vsix").open("ab") as stream:
                stream.write(b"tamper")
            tampered = service.verify_signature(
                directory / "first.vsix",
                directory / "first.vsix.sig.json",
            )

        self.assertEqual(first["artifact_digest"], second["artifact_digest"])
        self.assertTrue(first["compatibility_passed"])
        self.assertTrue(signature["verified"])
        self.assertTrue(verified["valid"])
        self.assertFalse(verified["trusted_publisher"])
        self.assertFalse(tampered["valid"])

    def test_real_process_restart_recovers_checkpoint_and_finishes_retry(self):
        script = ROOT / "scripts" / "run_task_recovery_acceptance.py"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            report_path = directory / "report.json"
            result = subprocess.run(
                [
                    sys.executable, str(script), "--report", str(report_path),
                    "--workspace-parent", str(directory),
                ],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["passed"])
        self.assertEqual(report["crash_exit_code"], 73)
        self.assertTrue(report["checks"]["checkpoint_reference_preserved"])
        self.assertTrue(report["checks"]["retry_completed"])

    def test_readiness_requires_trusted_publisher_and_full_sandbox(self):
        report = ProductReadinessService(ROOT.parent).report(
            ide_artifact={
                "signed": True, "artifact_digest": "digest",
                "compatibility_passed": True, "trusted_publisher": False,
            },
            sandbox_artifact={
                "passed": True, "os_enforced": True,
                "production_sandbox_ready": False,
            },
            restricted_token_artifact={
                "passed": True, "restricted_token": True,
                "filesystem_write_isolated": True,
                "appcontainer": {"enabled": False},
            },
            egress_proxy_artifact={
                "passed": True, "default_deny": True,
                "proxy_authentication": True,
                "dns_resolution_checked": True,
            },
            recovery_artifact={"passed": True},
            recovery_soak_artifact={
                "multi_worker_passed": True,
                "multi_hour_passed": False,
            },
        )
        checks = report["phases"]["p1_product_engineering"]["checks"]
        self.assertFalse(checks["signed_packaged_ide"])
        self.assertTrue(checks["os_sandbox_backend_probe"])
        self.assertFalse(checks["production_os_sandbox"])
        self.assertTrue(checks["restricted_token_filesystem_probe"])
        self.assertTrue(
            checks["authenticated_default_deny_egress_proxy"]
        )
        self.assertTrue(checks["process_restart_recovery"])
        self.assertTrue(checks["multi_worker_recovery_soak"])
        self.assertFalse(checks["multi_hour_recovery_soak"])
        self.assertFalse(report["product_ready"])


if __name__ == "__main__":
    unittest.main()
