"""Server-side provider credential resolution without browser-delivered secrets."""

from __future__ import annotations

import os
import re


def resolve_provider_key(provider: str, credential_ref: str | None = None) -> str:
    provider_name = re.sub(r"[^A-Z0-9_]", "_", provider.upper())
    if credential_ref:
        reference = re.sub(r"[^A-Z0-9_]", "_", credential_ref.upper())
        value = os.environ.get(f"CLAWVISION_CREDENTIAL_{reference}", "")
        if value: return value
    return os.environ.get(f"CLAWVISION_{provider_name}_API_KEY", "")
