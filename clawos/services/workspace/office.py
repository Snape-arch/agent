"""Office workflows and their domain dependencies."""
from __future__ import annotations
import json
from office_artifacts import create_pptx, create_xlsx, edit_xlsx, replace_pptx_text


class OfficeWorkspace:
    """Workspace office responsibilities."""

    def __init__(self, store, security):
        self.store = store
        self.security = security

    def create_spreadsheet(self, output_path, sheets=None, title=""):
        path = self.security.resolve_path(output_path)
        if path.suffix.lower() != ".xlsx":
            raise ValueError("output_path must end with .xlsx")
        artifact_path = create_xlsx(path, sheets or [{"name": "Sheet1", "rows": []}])
        return self._record_office_artifact(
            "spreadsheet", "create", title or path.stem, artifact_path,
            {"sheets": [sheet.get("name", "Sheet1") for sheet in (sheets or [])], "engine": "stdlib-openxml"},
        )


    def edit_spreadsheet(self, file_path, updates=None, output_path=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            raise ValueError("file_path must point to a readable .xlsx file")
        out = self.security.resolve_path(output_path) if output_path else path
        if out.suffix.lower() != ".xlsx":
            raise ValueError("output_path must end with .xlsx")
        artifact_path = edit_xlsx(path, updates or [], out)
        return self._record_office_artifact(
            "spreadsheet", "edit", out.stem, artifact_path,
            {"updates": updates or [], "engine": "stdlib-openxml"},
        )


    def create_presentation(self, output_path, title="", slides=None):
        path = self.security.resolve_path(output_path)
        if path.suffix.lower() != ".pptx":
            raise ValueError("output_path must end with .pptx")
        artifact_path = create_pptx(path, title=title or path.stem, slides=slides or [])
        return self._record_office_artifact(
            "presentation", "create", title or path.stem, artifact_path,
            {"slide_count": len(slides or []) or 1, "engine": "stdlib-openxml"},
        )


    def edit_presentation(self, file_path, replacements=None, output_path=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".pptx" or not path.is_file():
            raise ValueError("file_path must point to a readable .pptx file")
        out = self.security.resolve_path(output_path) if output_path else path
        if out.suffix.lower() != ".pptx":
            raise ValueError("output_path must end with .pptx")
        artifact_path = replace_pptx_text(path, replacements or {}, out)
        return self._record_office_artifact(
            "presentation", "edit", out.stem, artifact_path,
            {"replacements": list((replacements or {}).keys()), "engine": "stdlib-openxml"},
        )


    def _record_office_artifact(self, artifact_type, action, title, path, metadata):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO office_artifacts
                    (artifact_type, action, title, file_path, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(artifact_type), str(action), str(title), str(path),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = c.execute(
                "SELECT * FROM office_artifacts WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item
