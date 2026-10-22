# Office editing acceptance

This is a reproducible local editing baseline, not a claim of WPS feature parity.
The production `office_productivity` tool, workspace HTTP route, and legacy public
DOCX/XLSX/PPTX edit helpers use the same preservation service.

## Supported and verified operations

| Format | Operations | Verification and limits |
| --- | --- | --- |
| DOCX | Replace text spanning runs; edit body, tables, headers, footers and notes; add comments and tracked revisions | Preserve untouched package parts and namespaces. New replacement text inherits its first run's formatting. Comments/revisions require contiguous direct text runs; fields, links and existing review boundaries are not moved. |
| XLSX | Edit cells by actual worksheet name and package relationships, preserve style and numeric formatting, store literal leading `=` with `type: text` | Reject missing sheets, invalid addresses, merged-cell non-anchors and shared/array formula ranges. Invalidate dependent caches across worksheets, discard stale calculation chains, request recalculation on open. |
| XLSX recalculation | Optional installed LibreOffice Calc | Require the original formula count, a cache for every formula, no formula error cells and a valid package. Empty string formula results count as cached. LibreOffice may rewrite more package parts; the preceding edit preservation audit is not a claim that conversion preserves every unsupported feature. |
| PPTX | Replace text across runs in slides, tables and notes | Preserve untouched masters, themes, media and relationships. Does not edit animation timelines or arbitrary layout. |
| PDF | Extract, reorder, delete, rotate, merge pages and add text annotations | One-based pages apply to the current document after preceding operations. Reopen and verify page count. Document-level bookmarks, signatures and form relationships are not guaranteed across selection/merge. |

Edits build a temporary candidate beside the destination. Reopening and package
validation occur before replacement; failed edits or recalculation leave the
source and existing destination intact. The main service also detects a source
content change before publishing. Subsequent visual-quality reporting is separate
from this structural publication gate. Byte hashes and changed parts are evidence
of package preservation, not proof of semantic correctness or full XML-schema
conformance.

## Reproduction

From the repository root:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/office_editing_acceptance.py --out output/office-editing-acceptance
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos/tests
```

Add `--cross-app` to try the same DOCX with installed LibreOffice, Word and WPS
automation interfaces. Missing/failed engines remain failures of that comparison;
they are never silently substituted by LibreOffice. The latest local fixture run
passed all six edit/reopen/render checks: three formats rendered to one page each,
three formula caches were present, and numeric/conditional/empty-string values
were `50`, `passed`, and empty. All three rendered pages were visually inspected.
These are agent-authored development fixtures, not independent customer files.

The 2026-09-10 full current-worktree regression passed **560/560 in 295.749 s**.
After the final renderer-input isolation fix, editing/API tests passed **10/10**
and document benchmark tests passed **7/7**. Cross-application checks now give
each engine a separate byte-identical input and reserve an unrendered audit copy,
with the original digest captured before invoking any application.

The restricted run could not initialize Word/WPS automation. A normal-host retry
also failed to produce a usable comparison report and ended with a source-file
read `PermissionError`; this motivated input isolation. This does not establish
that WPS is absent, nor that a WPS compatibility gate has passed. A later retry
must produce actual engine PDFs and comparison evidence before claiming parity.

The test suite includes cross-run edits, comments/revisions, namespace retention,
non-sequential worksheet filenames, styles, cross-sheet cache invalidation,
literal formula-looking text, bad targets, broken relationships, invalid cell
coordinates, failed-batch preservation, PDF page order/rotation/annotations,
HTTP option forwarding and incomplete recalculation rejection.

## API examples

Use `POST /api/workspace/office/productivity` or the `office_productivity` tool.
`{"action":"capabilities"}` lists supported operations and limitations.

```json
{
  "action": "edit",
  "file_path": "C:/workspace/source.xlsx",
  "output_path": "C:/workspace/edited.xlsx",
  "updates": [{"sheet":"Data","cell":"B2","value":30}],
  "recalculate": true,
  "confirmed": true
}
```

```json
{
  "action": "edit",
  "file_path": "C:/workspace/source.pdf",
  "output_path": "C:/workspace/edited.pdf",
  "updates": [
    {"action":"extract","pages":[3,1]},
    {"action":"rotate","pages":[1],"degrees":90},
    {"action":"annotate","pages":[2],"text":"Review this evidence"}
  ],
  "confirmed": true
}
```

Paths must be inside configured allowed roots. Reading capabilities does not
write files. No external Office subscription or cloud upload is needed for the
local editing service; formula recalculation/rendering needs an installed engine.

## Remaining WPS-level acceptance

- Independently sourced complex documents and a working WPS/Word comparison.
- Full layout, charts, pivot tables, shapes, animations and rich formula editing.
- Reliable handling of macros, digital signatures, embedded objects and form
  relationships under transformation, including explicit unsupported cases.
- Interactive editing, undo/version history, recovery and a measured compatibility
  corpus across Office applications. The existing provider session scaffolding
  does not prove a functioning embedded editor or save-back integration.

Local models, `tools/`, generated files and runtime databases are excluded from
source control. No production user documents are automatically rewritten.
