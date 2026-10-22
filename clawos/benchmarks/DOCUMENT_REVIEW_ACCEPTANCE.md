# Source-linked critical-cell review acceptance (2026-08-31)

## Review-effort telemetry update — 2026-09-04

The review dialog now starts a monotonic timer only after all source crops for a
row have loaded. Each approve/reject submission can carry the active duration;
the server bounds it to zero–four hours, independently derives corrected and
inspected cell counts from authoritative before/after values, stores them in the
append-only review event and returns aggregate seconds per inspected/corrected
cell. Missing timings remain missing and are never estimated. The console states
when no real timing sample exists.

Timing is explicitly labelled `client_monotonic_clock_untrusted_telemetry`: it is
useful for product workload measurement but cannot authorize publication or
serve as tamper-proof benchmark truth. Automated benchmark correction does not
enter this metric. Focused tests cover bounded/optional timing, server-derived
edit counts and aggregation. The separate fixed OCR regression now reaches
60/60 automatically with zero worsened changes, but source review remains
enabled because the development set is neither independent nor document-disjoint.

## Outcome and boundary

Implemented an explicit correction workflow for positioned OCR evidence. Critical
values can be checked against original PDF crops, corrected without losing their
row/header context, and published only after source confirmation. This is NOT an
autonomous OCR accuracy or WPS parity claim.

### Recognizer evidence

- Column OCR remains the original value. Numeric/conditional cells additionally
  get two cell-crop recognition views (2x scale, PSM 6/7), subject to the existing
  90-second regional budget. Failed/incomplete views remain visible.
- Never replace text by voting or equate recognizer agreement with truth. The
  views use the same recognizer/model, so their errors are correlated.
- All recovered scanned-table cells, including headers and apparently
  high-confidence nonnumeric conditions, now require source confirmation. This
  also covers missing digits/negation that cannot be caught by a numeric regex.
- Fresh real OCR still scores **53/60 exact cells**, **3/5 critical anchors** on
  the unchanged four-table/two-page development corpus. Strict raw OCR CLI still
  exits **1**. Both erroneous critical anchors produce disagreements (**2/2**);
  a correct anchor appears in candidates for **1/2** (7倍, but not 95%+).

### Review and publication

- Console OCR queue has a source-review dialog with original cell crops, current
  values, alternative recognition views, explicit source-confirmation checkbox,
  approve/reject actions, and a separate knowledge-publication action.
- Submit requires every cell of the selected evidence row and its headers. Blank,
  missing or extra targets fail. Approved shared headers cannot silently change.
- Source SHA-256 and an extraction/metadata revision bind every form. Changed
  source, another review, or re-ingestion invalidates old forms. The comparison,
  cell/row/chunk updates, derived-knowledge retirement and audit insertion are
  committed together in a SQLite write transaction.
- Corrections update graph cells, rows, table values, headers, evidence units and
  chunks. Original text and before/after values remain in inspection/audit data.
  Stale legacy knowledge is archived in the review event and removed from active
  legacy rows; v2 records expire and their vector deletion is queued.
- Rejected rows remain withheld; when only rejections remain the document becomes
  `ready_with_exclusions`, not trustworthy/fully parsed. They can be reconsidered
  through the same source-review queue.
- Publishing is explicit and idempotent for reviewed chunks. Recheck current
  chunk content/state inside the write transaction. Publication enters the existing
  legacy-to-v2 absorption flow; it is not an unconditional claim of complete
  general semantic entailment.
- Background OCR jobs skip pending/rejected review documents and documents with
  review history, including partially failed documents. Explicit re-OCR can start
  a new revision; a sidecar/plain-text replacement cannot bypass pending review.

### Governed consumers

- `get_document_chunks` excludes review data by default; explicit
  `include_review=True` is reserved for source inspection. SQL filters run before
  limits. Text search, citation drafts, paper claim alignment and context paths
  consume the gated evidence.
- Default document/list/semantic-graph views strip raw OCR copies, pending tables,
  pending nodes and alternate hypotheses. A table is exported only once all its
  cells are approved; individual approved rows may already be cited.
- Legacy knowledge, v2 absorption/search, hybrid retrieval, reranking and the
  public vector-search path recheck authoritative review state. Vector paths also
  check active record/version rather than relying only on cached metadata.
- Structured Office table export rejects review-bearing tables. Markdown table
  export now handles the structured `rows` object and emits header separators
  instead of serializing dictionary keys character by character.
- Raw files, source crops and the dedicated inspection API remain readable for
  review. Arbitrary text supplied without provenance cannot be identified as a
  copied OCR value; this is a governed-evidence boundary, not a ban on file reads.

## Evidence

Run from workspace root with the project venv:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/scanned_table_benchmark.py --out clawos/output/review-20260831/raw
.\clawos\.venv\Scripts\python.exe clawos/scripts/document_review_benchmark.py --raw clawos/output/review-20260831/raw --out clawos/output/review-20260831/closed-loop
```

The first command is expected to fail the unchanged raw-text gates. The second
replays actual captured OCR through `KnowledgeService.run_ocr`, a temporary
MemoryStore, source-review service, publication, citation draft and Markdown
export. Frozen gold edits **simulate** user review: this does not count as real
user feedback, independent human labeling, or improved autonomous recognition.

- Workflow **14/14** checks pass, exit **0**.
- Simulated correction preserves **60/60** cell values and coordinates,
  **48/48** header links and **5/5** critical anchors.
- **16 rows** approved/published, **16 audit events**; repeat publication produces
  no duplicate knowledge. There are still **4 / 15** non-table review chunks on
  the respective pages, deliberately not auto-approved by table-only review.
- Both original critical cell crops were visually inspected. Actual browser UI
  testing in a loopback-only temporary DB corrected 7信/959%+, confirmed a shared
  header, blocked an unchecked submission, refreshed 2 -> 1 -> 0 pending rows and
  published two rows. This uses the actual console function and production review
  route handlers in an isolated harness, not a production account/DB or full
  dashboard navigation test.
- Reproducible UI harness: `scripts/document_review_preview.py`, loopback port
  18896, using those same captured artifacts and a temporary database. No paid API.
- `tests/test_document_review_loop.py`: 14 focused tests cover HTTP/crops,
  correction, shared headers, reject/approve, stale source/revisions, idempotence,
  raw-data withholding, old legacy/v2/vector state, Markdown and background jobs.
- New gates exposed and fixed two regression issues: SQLite read connections
  needed explicit close on Windows, and legacy manually cited ready documents
  without parsed chunks must not be mistaken for pending OCR. Knowledge-core
  **15/15**, routing/memory **34/34**, and frontend **45/45** regressions pass.
- Final full repository regression: **535/535 passed in 275.542 seconds**, after
  both fixes. Python compilation, bundled Node syntax and `git diff --check` pass.
  Existing SWIG, FastAPI/openpyxl and CRLF warnings are non-blocking.

## Remaining limits

- 95%+ still requires a human correction on this source; no automatic threshold
  tuning or corpus-label changes conceal that failure.
- All scanned cells need review, trading throughput for safety. Multi-view
  agreement is not calibrated confidence or an independent OCR engine.
- Broad physical-scan/merged/borderless/multi-page performance is unproven. Only
  a source-review workflow on the existing narrow corpus is accepted here.
- Independent document-disjoint human evaluation, fine-grained collaborative
  reviewer identity/permissions, and provenance for arbitrary pasted text remain
  outside this block. Existing local application access controls still apply.
- Production stored documents were not mass-reprocessed or edited during this
  development block. Older captures acquire the new multi-view candidates upon
  explicit re-OCR; existing pending chunks immediately use the default read gate.
