from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def safe_artifact_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "-", str(value or "").strip())
    return text.strip("-")[:80] or "artifact"


class ArtifactStorage:
    """Small artifact boundary for reports, workflow traces, and generated packages."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _resolve(self, relative_path: str | Path) -> Path:
        target = (self.root / relative_path).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("artifact path outside storage root")
        return target

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.describe(target, "json")

    def write_markdown(self, relative_path: str, title: str, sections: list[tuple[str, Any]]) -> dict[str, Any]:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", ""]
        for heading, content in sections:
            lines.extend([f"## {heading}", ""])
            if isinstance(content, str):
                lines.extend([content, ""])
            else:
                lines.extend([f"- {item}" for item in (content or ["none"])])
                lines.append("")
        target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.describe(target, "markdown")

    def describe(self, path: str | Path, kind: str = "file") -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        return {
            "kind": kind,
            "path": str(target),
            "exists": target.exists(),
            "bytes": target.stat().st_size if target.exists() else 0,
            "storage_root": str(self.root),
        }
