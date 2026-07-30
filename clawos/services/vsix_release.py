"""Reproducible VSIX packaging and detached publisher-signature evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VsixReleaseService:
    def __init__(self, extension_root: str | Path):
        self.root = Path(extension_root).expanduser().resolve()

    def package(self, output_path: str | Path) -> dict[str, Any]:
        package = json.loads(
            (self.root / "package.json").read_text(encoding="utf-8")
        )
        self._validate_package(package)
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        files = [
            path for path in sorted(self.root.rglob("*"))
            if path.is_file() and path.name not in {".DS_Store"}
            and "node_modules" not in path.parts
        ]
        manifest = self._manifest(package)
        content_types = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="json" ContentType="application/json"/>'
            '<Default Extension="js" ContentType="application/javascript"/>'
            '<Default Extension="md" ContentType="text/markdown"/>'
            '<Default Extension="vsixmanifest" ContentType="text/xml"/>'
            '</Types>'
        )
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            self._write(archive, "[Content_Types].xml", content_types.encode())
            self._write(
                archive, "extension.vsixmanifest", manifest.encode("utf-8")
            )
            for path in files:
                relative = path.relative_to(self.root).as_posix()
                self._write(archive, f"extension/{relative}", path.read_bytes())
        compatibility = self.verify_package(output)
        return {
            "schema": "clawos.vsix-package.v1",
            "artifact": str(output),
            "artifact_digest": sha256_file(output),
            "size_bytes": output.stat().st_size,
            "file_count": len(files) + 2,
            "extension_id": f"{package['publisher']}.{package['name']}",
            "version": package["version"],
            "reproducible_zip_metadata": True,
            "compatibility_passed": compatibility["valid"],
            "compatibility": compatibility,
        }

    @staticmethod
    def _write(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
        info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, content)

    @staticmethod
    def _validate_package(package: dict[str, Any]) -> None:
        required = {"name", "displayName", "version", "publisher", "engines", "main"}
        missing = sorted(required - set(package))
        if missing:
            raise ValueError("package.json missing: " + ", ".join(missing))
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(package["version"])):
            raise ValueError("extension version must be semantic x.y.z")

    @staticmethod
    def _manifest(package: dict[str, Any]) -> str:
        identity = escape(
            f"{package['publisher']}.{package['name']}"
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<PackageManifest Version="2.0.0" '
            'xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">'
            '<Metadata><Identity '
            f'Id="{identity}" Version="{escape(package["version"])}" '
            f'Publisher="{escape(package["publisher"])}" Language="en-US"/>'
            f'<DisplayName>{escape(package["displayName"])}</DisplayName>'
            f'<Description xml:space="preserve">{escape(package.get("description", ""))}</Description>'
            '<Tags>agent,coding,clawos</Tags>'
            '<Categories>Other</Categories>'
            '<Properties>'
            '<Property Id="Microsoft.VisualStudio.Code.Engine" '
            f'Value="{escape((package.get("engines") or {}).get("vscode", "*"))}"/>'
            '</Properties></Metadata>'
            '<Installation><InstallationTarget '
            'Id="Microsoft.VisualStudio.Code"/></Installation>'
            '<Dependencies/><Assets>'
            '<Asset Type="Microsoft.VisualStudio.Code.Manifest" '
            'Path="extension/package.json" Addressable="true"/>'
            '</Assets></PackageManifest>'
        )

    @staticmethod
    def verify_package(path: str | Path) -> dict[str, Any]:
        artifact = Path(path).expanduser().resolve()
        try:
            with zipfile.ZipFile(artifact) as archive:
                names = set(archive.namelist())
                package = json.loads(
                    archive.read("extension/package.json").decode("utf-8")
                )
                manifest = archive.read("extension.vsixmanifest").decode("utf-8")
                safe_names = all(
                    not name.startswith(("/", "\\")) and ".." not in Path(name).parts
                    for name in names
                )
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            return {"valid": False, "error": str(exc)}
        checks = {
            "required_entries": {
                "[Content_Types].xml", "extension.vsixmanifest",
                "extension/package.json", "extension/extension.js",
            }.issubset(names),
            "safe_archive_paths": safe_names,
            "manifest_identity": (
                f"{package.get('publisher')}.{package.get('name')}" in manifest
            ),
            "main_present": (
                "extension/" + str(package.get("main") or "").lstrip("./")
            ) in names,
        }
        return {"valid": all(checks.values()), "checks": checks}

    @staticmethod
    def sign(
        artifact_path: str | Path,
        private_key_pem: bytes,
        certificate_pem: bytes,
        signature_path: str | Path,
        *,
        trusted_publisher: bool = False,
    ) -> dict[str, Any]:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        artifact = Path(artifact_path).expanduser().resolve()
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        certificate = x509.load_pem_x509_certificate(certificate_pem)
        digest = sha256_file(artifact)
        signature = key.sign(
            bytes.fromhex(digest),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        record = {
            "schema": "clawos.vsix-signature.v1",
            "artifact_digest": digest,
            "algorithm": "rsa-pss-sha256",
            "signature": base64.b64encode(signature).decode("ascii"),
            "certificate_pem": certificate_pem.decode("ascii"),
            "certificate_fingerprint_sha256": certificate.fingerprint(
                hashes.SHA256()
            ).hex(),
            "subject": certificate.subject.rfc4514_string(),
            "not_before": certificate.not_valid_before_utc.isoformat(),
            "not_after": certificate.not_valid_after_utc.isoformat(),
            "trusted_publisher": bool(trusted_publisher),
            "signed_at": datetime.now(timezone.utc).isoformat(),
        }
        output = Path(signature_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        verified = VsixReleaseService.verify_signature(artifact, output)
        return {**record, "signature_path": str(output), "verified": verified["valid"]}

    @staticmethod
    def verify_signature(
        artifact_path: str | Path, signature_path: str | Path
    ) -> dict[str, Any]:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        artifact = Path(artifact_path).expanduser().resolve()
        record = json.loads(
            Path(signature_path).read_text(encoding="utf-8")
        )
        digest = sha256_file(artifact)
        checks = {
            "artifact_digest": digest == record.get("artifact_digest"),
            "algorithm": record.get("algorithm") == "rsa-pss-sha256",
            "certificate_present": bool(record.get("certificate_pem")),
        }
        try:
            certificate = x509.load_pem_x509_certificate(
                str(record.get("certificate_pem") or "").encode()
            )
            certificate.public_key().verify(
                base64.b64decode(record.get("signature") or ""),
                bytes.fromhex(digest),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            checks["cryptographic_signature"] = True
        except (ValueError, InvalidSignature):
            checks["cryptographic_signature"] = False
        return {
            "schema": "clawos.vsix-signature-verification.v1",
            "valid": all(checks.values()),
            "checks": checks,
            "trusted_publisher": bool(record.get("trusted_publisher")),
        }
