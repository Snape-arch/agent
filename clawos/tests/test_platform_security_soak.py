from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.egress_proxy import EgressProxyPolicy
from services.vsix_release import VsixReleaseService


class PlatformSecuritySoakTests(unittest.TestCase):
    @staticmethod
    def _publisher_chain() -> tuple[bytes, bytes, bytes]:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        now = datetime.now(timezone.utc)
        root_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        root_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "ClawOS Test Root"),
        ])
        root_certificate = (
            x509.CertificateBuilder()
            .subject_name(root_name).issuer_name(root_name)
            .public_key(root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=1), critical=True
            )
            .sign(root_key, hashes.SHA256())
        )
        leaf_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        leaf_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "ClawOS Publisher"),
        ])
        leaf_certificate = (
            x509.CertificateBuilder()
            .subject_name(leaf_name).issuer_name(root_name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
                critical=False,
            )
            .sign(root_key, hashes.SHA256())
        )
        return (
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            leaf_certificate.public_bytes(serialization.Encoding.PEM),
            root_certificate.public_bytes(serialization.Encoding.PEM),
        )

    def test_publisher_requires_matching_code_signing_trust_chain(self):
        key, certificate, trust = self._publisher_chain()
        result = VsixReleaseService.validate_publisher_identity(
            key, certificate, trust
        )
        self.assertTrue(result["valid"])
        self.assertTrue(result["trusted_publisher"])
        self.assertTrue(result["checks"]["code_signing_eku"])
        self.assertTrue(result["checks"]["trusted_chain"])

        wrong_key, _, _ = self._publisher_chain()
        mismatch = VsixReleaseService.validate_publisher_identity(
            wrong_key, certificate, trust
        )
        self.assertFalse(mismatch["trusted_publisher"])
        self.assertFalse(mismatch["checks"]["private_key_matches"])

    def test_production_egress_policy_denies_private_resolution(self):
        decision = EgressProxyPolicy(
            allowed_hosts=["127.0.0.1"], allowed_ports=[443]
        ).evaluate("127.0.0.1", 443)
        self.assertFalse(decision["allowed"])
        self.assertIn("non-public", decision["reason"])

    def test_multi_worker_crash_recovery_soak_is_not_multi_hour(self):
        script = ROOT / "scripts" / "run_multi_worker_recovery_soak.py"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            report_path = directory / "report.json"
            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--database", str(directory / "soak.db"),
                    "--report", str(report_path),
                    "--duration-seconds", "5", "--workers", "2",
                ],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["multi_worker_passed"])
        self.assertFalse(report["multi_hour_passed"])
        self.assertEqual(report["recovered_count"], 1)
        self.assertEqual(report["pending_task_count"], 0)


if __name__ == "__main__":
    unittest.main()
