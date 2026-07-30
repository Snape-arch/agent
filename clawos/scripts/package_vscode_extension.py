from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.vsix_release import VsixReleaseService


def development_identity() -> tuple[bytes, bytes]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "ClawOS Development Publisher"),
    ])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        certificate.public_bytes(serialization.Encoding.PEM),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension-root", default=str(ROOT / "integrations" / "vscode"))
    parser.add_argument("--output", default=str(ROOT.parent / "output" / "vscode" / "clawos-coding.vsix"))
    parser.add_argument("--private-key")
    parser.add_argument("--certificate")
    parser.add_argument("--development-signing", action="store_true")
    parser.add_argument("--trust-bundle")
    parser.add_argument("--code-cli")
    parser.add_argument("--report", default=str(ROOT.parent / "output" / "evidence" / "vscode-extension.json"))
    args = parser.parse_args()
    service = VsixReleaseService(args.extension_root)
    package = service.package(args.output)
    installation = {"attempted": False, "passed": False}
    if args.code_cli:
        acceptance_root = (
            Path(args.output).expanduser().resolve().parent
            / f"install-acceptance-{int(time.time() * 1000)}"
        )
        extensions = acceptance_root / "extensions"
        user_data = acceptance_root / "user-data"
        install = subprocess.run(
            [
                args.code_cli, "--install-extension", str(Path(args.output).resolve()),
                "--extensions-dir", str(extensions),
                "--user-data-dir", str(user_data), "--force",
            ],
            capture_output=True, text=True, timeout=60,
        )
        listed = subprocess.run(
            [
                args.code_cli, "--list-extensions", "--show-versions",
                "--extensions-dir", str(extensions),
                "--user-data-dir", str(user_data),
            ],
            capture_output=True, text=True, timeout=60,
        )
        expected = f"{package['extension_id']}@{package['version']}"
        installation = {
            "attempted": True,
            "passed": (
                install.returncode == 0
                and listed.returncode == 0
                and expected in listed.stdout
            ),
            "expected": expected,
            "install_exit_code": install.returncode,
            "list_exit_code": listed.returncode,
            "stdout_digest": hashlib.sha256(
                (install.stdout + listed.stdout).encode()
            ).hexdigest(),
        }
    signature = {}
    if args.development_signing:
        key, certificate = development_identity()
    elif args.private_key and args.certificate:
        key = Path(args.private_key).read_bytes()
        certificate = Path(args.certificate).read_bytes()
    else:
        key = certificate = b""
    if key:
        publisher_identity = service.validate_publisher_identity(
            key, certificate,
            Path(args.trust_bundle).read_bytes()
            if args.trust_bundle else b"",
        )
        signature = service.sign(
            args.output, key, certificate, str(args.output) + ".sig.json",
            trusted_publisher=publisher_identity["trusted_publisher"],
        )
        signature["publisher_identity"] = publisher_identity
    else:
        publisher_identity = {
            "valid": False, "trusted_publisher": False,
            "errors": ["publisher key and certificate were not supplied"],
        }
    report = {
        **package,
        "clean_install": installation,
        "compatibility_passed": bool(
            package["compatibility_passed"]
            and (not installation["attempted"] or installation["passed"])
        ),
        "signed": bool(signature.get("verified")),
        "signature": signature,
        "publisher_identity": publisher_identity,
        "trusted_publisher": bool(signature.get("trusted_publisher")),
        "production_distribution_ready": bool(
            package["compatibility_passed"]
            and (not installation["attempted"] or installation["passed"])
            and signature.get("verified")
            and signature.get("trusted_publisher")
        ),
        "truth_boundary": (
            "A development self-signature proves artifact integrity only. "
            "Production distribution requires an externally trusted publisher "
            "certificate and marketplace/clean-machine acceptance."
        ),
    }
    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["compatibility_passed"] and (
        not key or signature.get("verified")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
