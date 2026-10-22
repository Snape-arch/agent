# Raster region and table recovery — updated 2026-09-04

Status: **bounded development-corpus structural, text and review-effort acceptance passed**. Not generic document-layout understanding or WPS parity.

## 2026-09-04 automatic-recognition and effort closure

The unchanged source/labels now use bounded cell views plus a conservative
candidate selector. It ranks correlated OCR views with generic percentage/unit,
identifier-shape, document-local recurrence and near-identical multi-view
evidence. It contains no benchmark-specific replacement dictionary. Automatic
selection never clears `review_required`, never sets `auto_accepted`, and retains
the original transcription, candidates, scores and truth-boundary metadata.

The acceptance report now measures workload instead of treating simulated human
correction as OCR success. On the fixed development document, the pre-selector
baseline needs **7/60 cell edits and 9 character edits**; the final result needs
**0/60 and 0**, with **5/5 critical values exact**. All seven automatic changes
improve the frozen label distance and none worsen it. The first broader consensus
rule caused one real false correction (`响应` -> `啊应`); the new
`auto_changes_worsened == 0` gate rejected that run, and the rule was restricted
to identifier-only changes before the passing rerun.

| New workload/accuracy check | Fresh result |
| --- | ---: |
| Cell text exact | **60/60** |
| Critical text exact | **5/5** |
| Manual cell edits required | **7 -> 0** |
| Character edits required | **9 -> 0** |
| Automatic changes improved / worsened | **7 / 0** |
| Verified cells | **32** |
| Extra cell-verification compute | **61.688 s** |
| Whole two-page benchmark | **71.813 s** |

Reproduce with `--out clawos/output/regions-20260904/adaptive-v3`; the strict CLI
exits **0** and every structural, exactness, critical, non-table, workload,
no-regression and 90-second verification-budget gate passes. The two overlay
pages were visually checked again. These 60 correlated, agent-transcribed cells
were used during development, so 60/60 is regression evidence only—not held-out
accuracy, an independent confidence interval, physical-scan robustness or WPS
parity. Document-disjoint human labels remain required before a release claim.

## Implemented path

`RasterDocumentLayout` detects long bitmap rules, header-height bands and internal vertical column dividers. It supports header-framed tables with mostly borderless bodies, and regular fully ruled grids. Body rows come from common whitespace bands (small raster fragments are joined) or explicit full-grid rules. Unframed/borderless tables, detected merged headers, incomplete recognition and oversized candidates are not published as recovered tables. These conservative gates are not a learned document-layout model.

Each candidate is OCR'd by isolated columns using PSM 6, with horizontal rules removed in the temporary crops. Words are assigned back to geometric cells. This avoids whole-page column mixing and reduces a 3-column, 7-row table from 21 cell recognizer launches to 3 column launches. Original pages are unchanged. A 160-cell and 90-second regional budget bounds retries/work; failure keeps the original whole-page text and a candidate diagnostic instead of silently dropping the region.

The default local profile can select the **already installed** best Chinese model for CJK-heavy regional crops. Whole-page OCR stays fast Chinese/English. Explicit language/model-directory settings win; no download occurs during parsing. Without best Chinese installed, the fast profile remains available but the four-table result below is not guaranteed. The pinned installer from the previous block supports both profiles.

OCR results now include geometric table candidates and positioned OCR text blocks, with non-table semantic roles explicitly **unclassified**. This is not reliable automatic figure/chart/heading classification. Recovered cells include header references, precise page/row/column locators and word membership. The shared semantic graph publishes `cell_of`, `conditioned_by`, `word_in_cell` and `row_of`; row evidence repeats column headers and their values. Superseded flat OCR lines are excluded, so knowledge does not receive both a raw concatenation and a structured row as competing evidence.

Numeric-bearing scanned cells require verification regardless of engine confidence; rows inherit review state, as do rows depending on uncertain headers. They retain source coordinates but do not automatically become knowledge. This is deliberately conservative (model names containing digits also trigger review), not a calibrated detector of all recognition errors. Other raw-chunk consumers still require the universal review controls described in the previous OCR handoff.

## Fixed real development corpus

`scanned_table_regions_v1.json` contains four complete, header-bearing tables from two rasterized pages of the existing Chinese project plan: 60 cell texts, five critical numeric/condition/negation anchors and two non-table regions (prose and flowchart). Labels were visually transcribed by the agent. Source PDF SHA-256 is fixed; no independent human sign-off or document-disjoint held-out claim is made. This is a native Office export rasterized at 216 DPI, not a physical scanner sample.

| Check | Result |
| --- | ---: |
| Table region IoU >= .95 | 4/4 |
| Exact row/column shape | 4/4 |
| Cell bounds within table | 60/60 |
| Body-cell/header graph links | 48/48 |
| Non-table negative regions | 2/2 |
| Cell text exact (NFKC, whitespace/case normalized) | **53/60 = 88.33%** |
| Critical text exact | **3/5** |
| Numeric critical review flags | 3/3 |

Cell exactness requires >=90% and critical exactness requires 100%; the strict CLI correctly returns **exit 1**. Failures remain in `table-report.json`. Examples include `AI` versus `Al`, proper-name/spelling recognition, `7倍` versus `7信`, and `95%+` versus `959%+`. No expected values, thresholds or source text were rewritten to pass. The cell-text Wilson interval [0.778212, 0.942323] is only descriptive for correlated development cells, not population generalization.

Page OCR uses `recognition_text`, not expanded semantic row evidence: headers are intentionally repeated in evidence and must not be scored as OCR insertions. In the same source, p1 CER fell from 17.11% to **2.30%**, p2 is **5.28%**. CJK recall is **98.79% / 99.61%**, and text-position hit is **96.61% / 93.06%**. Both pages pass the old page-level OCR gates, but that does not supersede critical-cell failures.

QA overlays (`boxes-p1.png`, `boxes-p2.png`) were visually inspected: blue table bounds, green words, orange cells, red review-required cells. Row/column boundaries stay within the source tables; the flowchart remains outside recovered tables. The real console OCR service entry, using a temporary database and p1 scan, produced three tables, twelve structured data rows and twelve chunks. Document state was `needs_review`, numeric cells remained flagged, and the corrupted `959%` was **not promoted** to knowledge.

## Reproduce

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/install_ocr_models.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/install_ocr_models.py --profile best
.\clawos\.venv\Scripts\python.exe clawos/scripts/scanned_table_benchmark.py --out clawos/output/regions-20260831/final
.\clawos\.venv\Scripts\python.exe clawos/scripts/document_fidelity_benchmark.py --out clawos/output/regions-20260831/existing-regression --table-cells
```

The source PDF is the previous block's ignored `clawos/tmp/document-corpus/docx-a/ClawOS 项目计划书与技术说明书-最终版本.pdf`; see `DOCUMENT_OCR_ACCEPTANCE.md` for its source/render identity and recreation boundary. Reports, scan copies and overlays are ignored local artifacts, not committed data.

Existing fixed native-PDF/DOCX semantic, English recall-only OCR and 239-cell native-table gates still pass. Six new unit/integration tests cover regular grids, header-only grids, prose/frame/borderless/merged-header rejection, column-call count, failed recognition, missing-output denominators and condition-bearing knowledge chunks. No new DOCX generation or cross-Office round-trip claim is made in this block.

Final code validation: **521/521** full repository tests in **273.212 s**; focused region/OCR tests **19/19** in **0.992 s**; earlier semantic/OCR/native-table regression **24/24** in **27.241 s**. Compilation and diff checks pass. These software checks do not override the failed exact-cell quality gates.

## Remaining boundaries

- Critical cell recognition needs independent visual/different-engine verification or user confirmation; layout recovery alone is not enough.
- Truly borderless tables, spanning/merged cells, merged headers, cross-page continuations and general chart semantics are unsupported. A continuation row without its header is deliberately not counted as a complete table here.
- This detector is axis-aligned and clean-raster oriented. Skew, camera perspective, noise, broken rules, handwritten tables and vertical text need separate development/held-out corpora.
- Global OCR still runs before region refinement. A mixed native/image page with sufficient native header text can still bypass OCR. This block does not implement all-region OCR triggering.
- Broaden corpus by document, language and layout before release scoring; do not tune solely against these four development tables.
