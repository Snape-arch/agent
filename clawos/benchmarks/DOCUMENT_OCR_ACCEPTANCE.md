# Chinese OCR and evidence ingestion — 2026-08-31

Status: **implemented, partially accepted; not WPS parity**.

Update: [Regional table recovery](SCANNED_TABLE_ACCEPTANCE.md) now reconstructs four header-bearing tables and reduces Chinese p1 CER to 2.30%. Both Chinese pages pass page-level gates, but the new stricter 60-cell/critical-value gate remains failed (53/60 exact cells, 3/5 critical anchors). Results below describe the earlier whole-page baseline, not the current regional pipeline.

## What changed in the product path

- `DocumentOCRService` probes installed languages before recognition. Auto selects available simplified Chinese/English; an explicitly requested missing language fails rather than silently dropping that language. Missing engines, missing languages, empty recognition, timeouts and engine failures have distinct states.
- Fixed-revision official model installer verifies SHA-256 and refuses to overwrite different model files. Downloads are opt-in, workspace-local and ignored by Git; document content never leaves the machine. Fast is the default; the optional best profile changes only the Chinese model.
- TSV keeps word/block/paragraph/line identities, rejects invalid boxes/confidence values and transforms coordinates into unrotated PDF points. Recognition renders at 216 DPI, capped to 6000 pixels on the long edge.
- The semantic graph retains words for highlighting, but feeds **lines** into evidence/chunks. Chinese token boundaries are joined without deleting English word spaces. `word_of` links and page/line locators survive ingestion. Large horizontal gaps remain explicit separators and are marked structurally ambiguous, not inferred as valid table cells.
- Low-confidence/ambiguous chunks remain available for source inspection, but automatic knowledge promotion is skipped. Document state is `needs_review`; incomplete OCR pages remain `needs_ocr`, including mixed native/scanned documents. Engine confidence is not a calibrated probability of factual correctness.
- The console's existing `KnowledgeService.run_ocr` path now uses the same graph path for local PDFs, not the previous text-only pipeline. Review documents enter its queue. Its citation-draft endpoint withholds review-required chunks. This does **not** establish a universal review gate for every other raw-chunk consumer.
- Explicit/manual sidecar replacement remains supported. Its plain text has no trustworthy coordinate alignment; stale graph/layout metadata is removed and that limitation is recorded.

## Reproduction

Requirements: existing Tesseract executable and the project venv. Source references: [official fast models](https://github.com/tesseract-ocr/tessdata_fast), [official best models](https://github.com/tesseract-ocr/tessdata_best), [TSV/language CLI](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html). Model repositories use Apache-2.0 licensing; retain their license requirements when packaging model data.

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/install_ocr_models.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/install_ocr_models.py --profile best
.\clawos\.venv\Scripts\python.exe clawos/scripts/document_ocr_benchmark.py --source "clawos/tmp/document-corpus/docx-a/ClawOS 项目计划书与技术说明书-最终版本.pdf" --pages 1 2 --out clawos/output/ocr-20260831/final-chinese
.\clawos\.venv\Scripts\python.exe clawos/scripts/document_ocr_benchmark.py --source 参考文献/2305.16291v2.pdf --pages 1 --language eng --out clawos/output/ocr-20260831/final-english
```

`TESSERACT_CMD` overrides the executable; `TESSERACT_LANG` overrides auto (e.g. `eng` or `chi_sim+eng`); `TESSDATA_PREFIX` overrides model directory. For the optional best comparison, set `TESSDATA_PREFIX` to the absolute `tools/ocr/tessdata-best` path only for that process. No `.env` or system installation was changed.

The Chinese source PDF is the prior block's locally rendered real project DOCX, not a committed fixture. Recreate that rendered source before reproduction if the ignored tmp directory is absent. Its measured PDF SHA-256 is `111b212b9665f8811e7f87d9055706e10d0c5e9652146a0ab4c1effaef04c13a`. A different export engine/version may change the reference; compare the report's hash rather than treating another export as the same frozen artifact. Voyager source SHA-256 is `769a4e33ddeeb73870849232eece49afe882c2d146362e33917ccb432ba0efb8`.

Models:

| Model | Commit | SHA-256 |
| --- | --- | --- |
| fast Chinese | `87416418657359cb625c412a48b6e1d6d41c29bd` | `a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730` |
| fast English | same fast commit | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |
| best Chinese | `e12c65a915945e4c28e237a9b52bc4a8f39a0cec` | `4fef2d1306c8e87616d4d3e4c6c67faf5d44be3342290cf8f2f0f6e3aa7e735b` |

## Measured results — failures retained

Native real pages were rasterized into image-only PDFs. Reference text/positions come from the pre-rasterized source, not independent human labels. Metrics ignore punctuation, case and spacing; Chinese characters are counted rather than silently excluded. CER is Levenshtein character error rate and also penalizes order differences. Position-hit rate requires overlap with matching native text; its denominator excludes punctuation-only OCR tokens, while coordinate validity includes them. This denominator correction is regression-tested; thresholds were not relaxed.

| Development page/profile | Chinese recall | Text-position hit | CER | Gate |
| --- | ---: | ---: | ---: | --- |
| Project plan p1, fast | 95.52% | 91.52% | 17.11% | Fail: CER > 15% |
| Project plan p2, fast | 97.68% | 92.09% | 6.83% | Pass |
| Project plan p1, best Chinese | 94.83% | 92.23% | 17.11% | Fail: CER > 15% |
| Project plan p2, best Chinese | 99.61% | 94.79% | 4.04% | Pass |
| Voyager p1, English | N/A | 81.54% | 17.55% | Fail: precision, position and CER |

All measured boxes are within page bounds, but that alone does not mean their content is correct. Chinese p1 visibly includes table-cell/order errors and OCR substitutions; the best model does not solve them. Voyager includes diagram text, superscripts and a vertical arXiv stamp; native-text completeness/order is also a reference limitation for this page. The strict English v2 gate remains failed; do not describe all mismatches as proven OCR errors or silently exclude the diagram to pass. Independent region/order annotation is the next step.

The older **recall-only English gate still passes** (word recall 0.959677, mean engine confidence 0.900747, bbox validity 1). This does not supersede the stricter failures above. The unchanged seven-document semantic and 239-cell table gates also pass. No WPS/Word round-trip or new Office output was measured in this block.

Artifacts are in ignored `clawos/output/ocr-20260831/`: source scans, per-page graphs, coordinate overlays and JSON reports. Source p1/p2 and all three default-profile overlays were visually inspected. Real service-entry ingestion of Chinese scan p1 produced **16 chunks, 8 review chunks, 8 promoted knowledge items**, preserved page locators and one review-queue document; a temporary database was used, not the user's library.

## Remaining acceptance work

Code validation: **515/515** repository tests passed in **271.150 s** after the console-entry integration; focused OCR/API/memory tests **47/47** in **5.469 s**. Compilation and diff checks pass. These software tests do not override the failed real-document quality gates above.

1. Region-aware scanned table/layout recovery, not more global OCR language switches. Preserve row/header conditions and exclude icon/line-art recognition from factual evidence.
2. Independent source-region, reading-order and critical numeric/negation truth labels; freeze document-disjoint scans. Current pages are development proxies; confidence intervals over their correlated characters would not establish generalization.
3. Review/confirm workflow with safe evidence promotion and consistent gates across every citation consumer, not only ingestion and the basic citation-draft endpoint.
4. Physical scanner degradation, handwriting, skew/orientation correction, traditional Chinese/vertical scripts, and complex formulas remain unevaluated. Cropped pages with a nonempty native header can still bypass the current low-text OCR trigger; mixed native/image-region detection remains needed.
5. Borderless/merged/multi-page tables, editable equations, editable reconstruction and broader Office round-trip coverage remain prerequisites for WPS-level claims.
