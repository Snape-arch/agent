from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import tempfile
from pathlib import Path
from typing import Any


OUTPUT_KEYS = {
    "path", "output_path", "markdown_path", "pdf_path", "diff_path",
    "patch_path", "workbook", "presentation", "document", "report_path",
    "persisted_report", "json_path",
}
PREVIEWABLE_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".md", ".markdown", ".txt", ".csv", ".json", ".diff", ".patch",
}


class ArtifactDeliveryService:
    """Register generated files and expose opaque, root-scoped delivery IDs."""

    def __init__(self, registry_path: str | Path, allowed_roots: list[str | Path]):
        self.registry_path = Path(registry_path).expanduser().resolve()
        self.allowed_roots = tuple(Path(item).expanduser().resolve() for item in allowed_roots)

    def collect(self, tool_calls: list[dict[str, Any]], *, task_id: Any = None) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for call in tool_calls or []:
            tool = str(call.get("name") or "tool")
            result = call.get("result") or {}
            payload = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
            if isinstance(payload, dict) and payload.get('preview') is True and not payload.get('written'):
                continue
            for path in self._paths(payload):
                key = os.path.normcase(str(path))
                if key in seen:
                    continue
                seen.add(key)
                item = self.register(path, source_tool=tool, task_id=task_id)
                if item:
                    artifacts.append(item)
        return artifacts

    def register(self, path: str | Path, *, source_tool: str = "", task_id: Any = None) -> dict[str, Any] | None:
        target = Path(path).expanduser().resolve()
        if not target.is_file() or not self._allowed(target):
            return None
        stat = target.stat()
        digest = self._sha(target)
        artifact_id = hashlib.sha256(f"{target}|{digest}".encode("utf-8")).hexdigest()[:24]
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        suffix = target.suffix.lower()
        item = {
            "id": artifact_id,
            "name": target.name,
            "path": str(target),
            "bytes": stat.st_size,
            "sha256": digest,
            "mime_type": mime,
            "format": suffix.lstrip(".") or "file",
            "source_tool": source_tool,
            "task_id": task_id,
            "created_at": int(time.time()),
            "download_url": f"/api/artifacts/{artifact_id}/download",
            "preview_url": f"/api/artifacts/{artifact_id}/preview" if suffix in PREVIEWABLE_SUFFIXES else "",
        }
        from .file_transactions import _file_lock
        with _file_lock(self.registry_path):
            registry = self._load()
            registry[artifact_id] = item
            self._write(registry)
        return {key: value for key, value in item.items() if key != "path"}

    def resolve(self, artifact_id: str) -> tuple[dict[str, Any], Path]:
        item = self._load().get(str(artifact_id or ""))
        if not item:
            raise KeyError("artifact not found")
        path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not path.is_file() or not self._allowed(path):
            raise FileNotFoundError("artifact file is unavailable")
        if self._sha(path) != item.get("sha256"):
            raise ValueError("artifact changed after registration")
        return item, path

    def _paths(self, value: Any, *, parent: dict[str, Any] | None = None) -> list[Path]:
        rows: list[Path] = []
        if isinstance(value, dict):
            artifact_like = any(key in value for key in ("bytes", "sha256", "format", "kind", "valid", "written", "operation"))
            for key, child in value.items():
                if isinstance(child, str) and child.strip() and (key in OUTPUT_KEYS and (key != "path" or artifact_like)):
                    rows.append(Path(child))
                elif key == "images" and isinstance(child, list):
                    rows.extend(Path(item) for item in child if isinstance(item, str) and item.strip())
                elif key not in {"arguments", "inputs"}:
                    rows.extend(self._paths(child, parent=value))
        elif isinstance(value, list):
            for child in value:
                rows.extend(self._paths(child, parent=parent))
        return rows

    def _allowed(self, path: Path) -> bool:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _load(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            return {}
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError('artifact registry must be an object; recover it before registering files')
            return value
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError('artifact registry is unreadable; recover it before registering files') from exc

    def _write(self, payload: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.artifacts-',suffix='.tmp',dir=self.registry_path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as handle:
                json.dump(payload,handle,ensure_ascii=False,indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            replace_error = None
            for attempt in range(8):
                try:
                    os.replace(temporary,self.registry_path)
                    replace_error = None
                    break
                except PermissionError as exc:
                    replace_error = exc
                    if attempt == 7:
                        raise
                    time.sleep(0.025 * (attempt + 1))
            if replace_error is not None:
                raise replace_error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
