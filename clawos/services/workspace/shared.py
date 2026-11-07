"""Shared workflows and their domain dependencies."""
from __future__ import annotations
import json
import hashlib
import re
import uuid


class WorkspaceValues:
    """Workspace shared responsibilities."""

    @staticmethod
    def _safe_filename(name):
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(name)).strip("._")
        return safe[:80] or f"report_{uuid.uuid4().hex[:8]}"


    @staticmethod
    def _summarize_text(text):
        clean = " ".join(str(text or "").split())
        return clean[:600]


    @staticmethod
    def _file_hash(path):
        import hashlib
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()


    @staticmethod
    def _decode_record(row, json_keys):
        item = dict(row)
        for key in json_keys:
            item[key] = json.loads(item.get(key) or ("[]" if key == "diarization" else "{}"))
        return item
