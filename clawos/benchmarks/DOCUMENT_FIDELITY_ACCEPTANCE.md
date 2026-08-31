# Document fidelity acceptance — 2026-08-30

Status: **partial; not WPS parity and not a release sign-off**.

Latest: [Raster region/table acceptance](SCANNED_TABLE_ACCEPTANCE.md) separates recovered geometry/relations (4/4 tables, 60/60 cell bounds, 48/48 header links) from still-imperfect OCR text (53/60 exact cells, 3/5 critical anchors). Native-document regression gates remain unchanged and passing.

## Chinese OCR update (2026-08-31)

Local Chinese/English OCR now preserves line evidence, word coordinates, review flags and partial-failure states through both ingestion and the console OCR service. Pinned model installation and CJK-sensitive, position-aware evaluation are available. Default Chinese page recall is 95.52% / 97.68%, but only one of two pages passes all gates; complex table reading order remains a failure. The stricter English v2 page gate also fails despite the old recall-only gate passing. See [OCR acceptance and retained failures](DOCUMENT_OCR_ACCEPTANCE.md). The original semantic and 239-cell table regression gates still pass. This is a separate partial acceptance block, not a WPS completion claim.

## Table reconstruction update (second development block)

The three missing tables below are now reconstructed. The same seven-document v1 semantic corpus passes its existing gates: type/page anchors 53/53, actual-object relations **7/7** (previously 4/7), count constraints still 26/28. The two reference-count annotation-unit discrepancies remain unchanged.

New versioned `document_table_cells_v1.json` checks four real tables from three PDFs, including the neighbouring MemGPT table as a separate region. Results: **239/239 cell values**, **126/126 small-type annotations**, **22/22 headers**, **33/33 row contexts and condition-bearing evidence rows**, **239/239 coordinate/link checks**, and **8/8 table geometry/shape checks**. Cell-value Wilson 95% interval is [0.984181, 1]; annotation interval is [0.970414, 1]. These are descriptive intervals for correlated development examples, not held-out/generalization claims.

Implementation uses caption-local horizontal rules, header whitespace and glyph coordinates, not a whole-page text grid. Same-width successive tables and adjacent column tables remain distinct. Executor groups and continuation-row parent models are retained. Small type is separately stored with `meaning=not_inferred`; the parser does not silently invent a standard-deviation interpretation. A stable quantized glyph sort fixes float-tie ligature transposition. Unlabelled/prose/ambiguous sparse regions fail closed.

The graph now contains cell/header/group links and row evidence with the caption, group and parent conditions. Superseded flat table fragments are excluded from knowledge evidence. Office generation consumes recovered tables, splits distinct experimental groups, expands continuation labels and keeps human-readable source filename/page in prose with precise locators in metadata. This preserves semantics; it is not facsimile layout reproduction.

Updated command (also creates and renders a real recovered MemGPT table):

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\document_fidelity_benchmark.py --out clawos\output\document-tables-20260830-final --table-cells --cross-office
```

All five gates (original semantic, OCR, cell corpus, existing stress-fixture Office comparison and recovered-table Office comparison) pass. The original v1 manifest has not been loosened. Maintainer sign-off remains false. The remaining roadmap is borderless/unruled and spanning tables, merged headers, scanned/Chinese documents, exact editable equations, independent document-disjoint labels and broader real-document editing/round-trip tests.

Validation for this block: full suite **502/502** in **264.110 s**; final source-label display change followed by **12/12** table/Office tests in **51.739 s**. The recovered-table report has one page in all three Office engines, token recall 1.0, and raster similarities 0.994193 (LibreOffice) / 0.998222 (WPS) versus Word. Final recovered and stress-fixture DOCX files were rendered and all five pages visually reviewed; table content, source labels, footnote body and repeating headers remain visible. This tests regenerated report readability, not reproduction of the source paper's original typography.

## Historical baseline before table reconstruction

Final code regression: **495 tests passed in 260.656 seconds**. The final generated DOCX was rendered and all four page images inspected; the deliberately explicit page breaks and tracked replacement are fixture requirements. No clipped text or broken repeated headers was observed. Cross-engine token recall versus Word was 0.992767; normalized raster similarity was 0.989996 for LibreOffice and 0.972558 for WPS. These numbers are fixture-specific, not general product quality scores.

## Reproduce

From the repository root, using the project environment:

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\document_fidelity_benchmark.py --out clawos\output\document-fidelity-20260830 --cross-office
```

`--cross-office` explicitly opts into hidden local Word/WPS automation. LibreOffice, registered Word/WPS COM applications and Tesseract are required for their respective live checks. No cloud upload is needed. Without the flag, only semantic and OCR evaluation runs. A failed acceptance gate returns exit code 1; this is not necessarily an execution crash. Reports are generated under the selected output directory. Every cross-application run uses new export paths so stale PDFs cannot satisfy a gate.

## Evidence and its limits

- The frozen, SHA-256-identified corpus contains five real research PDFs and two project DOCX files. Its 53 type/page assertions, seven relation assertions and 28 count constraints are **development regression labels**, not an independent held-out benchmark or production user feedback.
- Type and rendered-page assertions: 53/53 each; descriptive Wilson 95% interval [0.932418, 1]. These selected anchors do not establish exhaustive extraction recall.
- Actual-object relation recovery: 4/7; descriptive Wilson 95% interval [0.250458, 0.841780]. Caption-derived placeholders no longer count as recovered figures/tables. Even successful relations currently check target kind, not independently labelled bounding-box overlap or full cell accuracy.
- Count constraints: 26/28. Reference counting needs annotation-unit review: multi-citation blocks are now split into citations. Do not silently change the frozen bounds to turn failures green.
- English OCR: a real Voyager PDF page was rasterized into an image-only PDF; word recall 0.943548, coordinate validity 1.0 and mean OCR confidence 0.871951. This is one machine-printed English sample, not Chinese/handwriting/scanner robustness.
- Word/WPS/LibreOffice: the same generated stress fixture exports to four pages in each engine. Comparison measures token retention, normalized raster similarity, page count, and a separate hard check for footnote/endnote text. Rendering parity does not prove full editing or OOXML round-trip parity.
- Parser `quality.score` measures structural integrity only; `semantic_accuracy_evaluated` is false. A structural score of 100 must not be advertised as perfect document understanding.
- Maintainer sign-off remains false; release parity claims remain disabled. Within-document assertions are correlated; the intervals are not cross-document population generalization estimates.

The 2026-08-27 semantic and cross-application reports are marked superseded: inferred objects and missing footnote text were previously insufficiently checked. Preserve them for audit, not as current acceptance evidence.

## Previously unresolved failures (now covered by cell-level regression)

1. Voyager, page 7, “Table 1: Tech tree mastery”: table caption recovered, structured table missing.
2. MemGPT, page 5, “Table 2. Deep memory retrieval”: table caption recovered, structured table missing; neighbouring columns contain another table.
3. SkillOS, page 7, “Table 1 | Experiment results”: table caption recovered, structured table missing; grouped executor headers and value/uncertainty pairs require hierarchy.

Diagnostic experiments with full-page text-based table detection produced prose-as-cells, truncated columns and merged data rows. Default alternative detection recovered a Voyager region but merged several rows/columns. These outputs were deliberately not installed as a successful fallback.

## Original follow-up plan (items 1–2 implemented; independent review still pending)

1. Add bounded table-region detection, then row/column reconstruction within each region. Retain original word coordinates and distinguish detected geometry from unresolved cell semantics.
2. Add independently reviewed cell-level labels for the three failures: region/page, exact numeric text, row label, column header, grouped header and uncertainty relationship. Include negative examples of nearby prose and adjacent tables. Freeze new labels as a versioned corpus; do not overwrite v1.
3. Require no lost experimental conditions or numeric substitutions in these cases, and test table-to-answer citations against the labelled cells. Keep a document-disjoint held-out split before making broader quality claims.
4. Expand coverage to vector figures, native structured equations versus visual-only preservation, Chinese OCR, scanned/rotated pages and multiple-page evidence. Verify comments/revisions structurally as well as visually: headless PDF exports do not reliably display comments.
5. Extend the cross-application corpus beyond one generated fixture to existing complex customer-like documents with reviewed round-trip edits. A single four-page fixture cannot close the WPS-level goal.
