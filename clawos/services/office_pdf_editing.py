"""PDF page operations; all mutations target the caller's temporary candidate."""
from pathlib import Path
import fitz


def edit_pdf(source: Path, output: Path, updates: list[dict], resolve_path) -> dict:
    if not updates:
        raise ValueError("PDF editing requires page operations")
    operations = []
    with fitz.open(source) as document:
        if document.needs_pass:
            raise ValueError("encrypted PDF must be unlocked before editing")
        for update in updates:
            action = update.get("action")
            def pages():
                values = update.get("pages")
                if not isinstance(values, list) or not values or any(type(v) is not int or not 1 <= v <= len(document) for v in values):
                    raise ValueError("pages must contain valid one-based page numbers")
                if len(set(values)) != len(values):
                    raise ValueError("duplicate page numbers are not supported")
                return [v-1 for v in values]
            if action == "rotate":
                selected = pages()
                degrees = update.get("degrees")
                if type(degrees) is not int or degrees % 90:
                    raise ValueError("rotation must be an integer multiple of 90 degrees")
                for index in selected:
                    page = document[index]
                    page.set_rotation((page.rotation + degrees) % 360)
            elif action in {"extract", "reorder", "delete"}:
                selected = pages()
                if action == "reorder" and set(selected) != set(range(len(document))):
                    raise ValueError("reorder requires every page exactly once")
                if action == "delete":
                    selected = [i for i in range(len(document)) if i not in selected]
                if not selected:
                    raise ValueError("PDF must retain at least one page")
                document.select(selected)
            elif action == "merge":
                other_path = resolve_path(update.get("file_path") or "")
                if not other_path.is_file() or other_path.suffix.lower() != ".pdf":
                    raise ValueError("merge requires an existing PDF")
                with fitz.open(other_path) as other:
                    if other.needs_pass:
                        raise ValueError("cannot merge an encrypted PDF")
                    document.insert_pdf(other)
            elif action == "annotate":
                selected = pages()
                content = str(update.get("text") or "").strip()
                if not content or len(content) > 10000:
                    raise ValueError("annotation text must contain 1 to 10000 characters")
                for index in selected:
                    document[index].add_text_annot((24, 24), content)
            else:
                raise ValueError(f"unsupported PDF operation: {action}")
            operations.append({"action": action, "page_count_after": len(document)})
        expected_pages = len(document)
        document.save(output, garbage=3, deflate=True)
    with fitz.open(output) as reopened:
        if len(reopened) != expected_pages:
            raise ValueError("PDF reopen page-count mismatch")
    return {"schema": "clawos.pdf-page-edit.v1", "operations": operations,
            "pages": expected_pages, "reopened": True,
            "truth_boundary": "Page operations preserve page content; merge and selection do not guarantee document-level bookmarks, signatures or interactive form relationships."}
