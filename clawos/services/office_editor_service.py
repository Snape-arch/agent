from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Any


class OfficeEditorService:
    """Safe, provider-neutral session configs for embedded Office editors."""

    PROVIDERS = {
        "wps": "iframe+jssdk",
        "onlyoffice": "DocsAPI+callback",
        "collabora": "WOPI+postMessage",
    }

    def capabilities(self) -> dict[str, Any]:
        providers = {
            "wps": {
                "configured": bool(os.environ.get("WPS_WEBOFFICE_SDK_URL") and os.environ.get("WPS_WEBOFFICE_LAUNCH_URL")),
                "transport": self.PROVIDERS["wps"], "required": ["WPS_WEBOFFICE_SDK_URL", "WPS_WEBOFFICE_LAUNCH_URL"],
            },
            "onlyoffice": {
                "configured": bool(os.environ.get("ONLYOFFICE_DOCUMENT_SERVER_URL") and os.environ.get("ONLYOFFICE_JWT_SECRET")),
                "transport": self.PROVIDERS["onlyoffice"], "required": ["ONLYOFFICE_DOCUMENT_SERVER_URL", "ONLYOFFICE_JWT_SECRET"],
            },
            "collabora": {
                "configured": bool(os.environ.get("COLLABORA_ONLINE_URL") and os.environ.get("CLAWOS_PUBLIC_BASE_URL")),
                "transport": self.PROVIDERS["collabora"], "required": ["COLLABORA_ONLINE_URL", "CLAWOS_PUBLIC_BASE_URL"],
            },
        }
        return {"providers": providers, "configured": [name for name, value in providers.items() if value["configured"]]}

    def create_session(
        self, provider: str, *, artifact_id: str, file_name: str, sha256: str,
        public_base_url: str, mode: str = "edit", user_name: str = "ClawOS User",
    ) -> dict[str, Any]:
        provider = str(provider or "").lower()
        if provider not in self.PROVIDERS:
            raise ValueError("provider must be wps, onlyoffice or collabora")
        if mode not in {"view", "edit"}:
            raise ValueError("mode must be view or edit")
        capabilities = self.capabilities()["providers"][provider]
        if not capabilities["configured"]:
            raise RuntimeError(f"{provider} editor is not configured")
        base = self._safe_base(public_base_url)
        artifact_url = f"{base}/api/artifacts/{urllib.parse.quote(artifact_id)}/download"
        session_id = secrets.token_urlsafe(18)
        expires_at = int(time.time()) + 900
        common = {"provider": provider, "session_id": session_id, "expires_at": expires_at, "mode": mode}
        if provider == "wps":
            sdk = self._safe_url(os.environ["WPS_WEBOFFICE_SDK_URL"])
            launch = self._safe_url(os.environ["WPS_WEBOFFICE_LAUNCH_URL"])
            separator = "&" if "?" in launch else "?"
            return {**common, "mount": {"type": "wps-jssdk", "sdk_url": sdk, "config": {"url": f"{launch}{separator}artifact_id={urllib.parse.quote(artifact_id)}", "mount": "#office-editor-mount"}}}
        if provider == "onlyoffice":
            server = self._safe_base(os.environ["ONLYOFFICE_DOCUMENT_SERVER_URL"])
            callback_sig = hmac.new(os.environ["ONLYOFFICE_JWT_SECRET"].encode(), f"{session_id}:{artifact_id}:{expires_at}".encode(), hashlib.sha256).hexdigest()
            callback = f"{base}/api/office/editor/callback/onlyoffice/{session_id}?artifact_id={urllib.parse.quote(artifact_id)}&expires={expires_at}&sig={callback_sig}"
            config = {
                "document": {"fileType": Path(file_name).suffix.lstrip(".").lower(), "key": sha256[:40], "title": file_name, "url": artifact_url},
                "documentType": self._document_type(file_name),
                "editorConfig": {"callbackUrl": callback, "mode": mode, "user": {"id": hashlib.sha256(user_name.encode()).hexdigest()[:16], "name": user_name}},
            }
            token = self._jwt(config, os.environ["ONLYOFFICE_JWT_SECRET"], expires_at)
            return {**common, "mount": {"type": "onlyoffice-docsapi", "script_url": f"{server}/web-apps/apps/api/documents/api.js", "config": {**config, "token": token}}}
        server = self._safe_base(os.environ["COLLABORA_ONLINE_URL"])
        wopi = f"{base}/api/office/editor/wopi/files/{urllib.parse.quote(artifact_id)}"
        iframe = f"{server}/browser/dist/cool.html?WOPISrc={urllib.parse.quote(wopi, safe='')}"
        return {**common, "mount": {"type": "collabora-wopi", "iframe_url": iframe, "wopi_src": wopi}}

    @staticmethod
    def _document_type(name: str) -> str:
        suffix = Path(name).suffix.lower()
        return "cell" if suffix in {".xlsx", ".xls", ".csv"} else "slide" if suffix in {".pptx", ".ppt"} else "word"

    @staticmethod
    def _safe_url(value: str) -> str:
        parsed = urllib.parse.urlparse(str(value))
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("editor URLs must use HTTPS or localhost HTTP")
        if parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("editor URL is invalid")
        return value.rstrip("/")

    @classmethod
    def _safe_base(cls, value: str) -> str:
        return cls._safe_url(value).rstrip("/")

    @staticmethod
    def _jwt(config: dict[str, Any], secret: str, expires_at: int) -> str:
        encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
        header = encode({"alg": "HS256", "typ": "JWT"})
        payload = encode({**config, "exp": expires_at})
        signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
        return f"{header}.{payload}.{signature}"

    @staticmethod
    def validate_callback(session_id: str, artifact_id: str, expires_at: int, signature: str) -> bool:
        secret = os.environ.get("ONLYOFFICE_JWT_SECRET", "")
        if not secret or int(expires_at) < int(time.time()):
            return False
        expected = hmac.new(secret.encode(), f"{session_id}:{artifact_id}:{int(expires_at)}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature or ""))
