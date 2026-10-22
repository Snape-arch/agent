# Document Studio acceptance — 2026-10-03

This block continues from `f6b02a4`. It improves the existing application rather than claiming parity with Feishu Docs. Source, tests and this record are deliverables; screenshots, databases and runtime reports stay in ignored `clawos/output`.

## Delivered behavior

- Structured transactions format selections across paragraphs, headings, quotes, lists and rich table cells. Cross-block typing, cut, rich HTML paste, Enter split, Shift+Enter soft break and boundary Backspace/Delete preserve surrounding text and can be undone. Continuous replacement typing belongs to one undo transaction. Separate cell replacement remains bounded to a single cell.
- Tables retain validated inline marks in `cell_inline` alongside their legacy Markdown projection. Non-overlapping concurrent cell edits merge even when both users first migrate a plain table. Conflicting edits or simultaneous structural/content changes retain an explicit conflict. Header cells use native `th scope=col`; Alt+arrow navigates cells.
- Table formulas evaluate bounded arithmetic, A1:L50 references, ranges, SUM/AVERAGE/AVG/MIN/MAX/COUNT/ABS/SQRT/ROUND, with explicit reference, cycle, syntax, numeric and division errors. Numeric inputs come from plain rich text, so formatting a number does not break a formula. Results are recomputed locally and do not execute code. Reading displays results; editing keeps formula source available.
- Display LaTeX blocks render with locally vendored KaTeX 0.19.0, license and fonts, producing HTML plus MathML. Formula source is limited to 2,000 characters; expansion and sizing are bounded, trust is disabled, and external link/image/HTML commands show a clear error. Captions remain available. The supported configuration follows [KaTeX options](https://katex.org/docs/options) and [browser integration](https://katex.org/docs/browser).
- Authenticated selection payloads contain version-bound UTF-16 anchor/focus offsets, independent block and table-cell endpoints. The server validates both endpoints, current/retained versions, identity and ACL in a transaction. SSE carries cursor updates; overlays use actual text ranges and never include block-menu text. A dirty draft immediately hides overlays; remote patches republish positions against the new saved version. Revocation denies further writes and live access.
- Learning Studio is the existing visual reference: dark ink, restrained green, one font stack, consistent heading/label scales, spacing and focus treatment. The shared stylesheet covers the work console, education pages, literature reader, documents, meetings and data workspace. Dark education cards retain light text. Document navigation becomes searchable, tools move into quiet menus, and title/body/table/code/math have deliberate typography in one aligned page column. Reading hides editing chrome and exposes offscreen document structure for accessibility.

## Actual evidence

| Check | Result |
| --- | --- |
| Full isolated Python regression | **721/721, 387.089 s**, isolated workspace `output/regression/1d4d6eb73a8c4a6bbc4fc99a3651ba70` |
| New advanced document backend tests | Six tests included in full regression: rich-cell roundtrip/migration merge, conflict, validation/math bounds, UTF-16/version/revocation, long rich projection resave, cross-block/cell endpoint validation |
| Node regression | 17/17, 295.2494 ms |
| CI-owned Chromium functional flow | 12 checks passed, two independent authenticated contexts, no page errors |
| Cursor geometry | Actual x = expected x = 479.65625 CSSpx; selected character width 9.5 CSSpx; cross-block and rich-cell selections also passed |
| Accessibility automation | Nine desktop routes, five rich-document states and three additional mobile education routes: zero axe-core 4.13.0 WCAG-tag violations; incomplete/manual items remain |
| Browser accessibility tree | Native document heading, table and columnheader roles verified; MathML fraction structure verified in DOM. This does not certify spoken math output |
| 390 × 844 touch emulation | Eleven routes have clientWidth = scrollWidth = 390; document toolbar/navigation scroll internally |
| Production database | SHA-256 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`, unchanged |

The functional script tests formatting toggles/selection retention; copy without menu labels; grouped replacement undo; split/join; soft break/cut/rich paste undo; rich-cell numeric formulas; local math/external-image rejection; precise caret/selection; cross-block/cell positions; hiding stale draft cursors; permission revocation; and reading semantics. Its isolated contexts use synthetic data and no user Chrome profile.

A first full run executed 721 tests with one existing self-evolution measured-gate failure under concurrent browser load: frozen candidate passed 29/30 and P95 940.464 ms versus 573.258 ms baseline. Its release stayed rejected. No gate or quality assertion was loosened. An isolated single-module rerun passed 8/8 in 37.492 s. The final serial full run passed 721/721. Subsequent changes only affected frontend focus/style/cache versions; affected browser/accessibility/reflow checks were rerun. Existing FastAPI, openpyxl and SWIG warnings remain non-blocking.

Actual screenshots were inspected before and after implementation. Evidence directory: `output/document-studio-20261003` (ignored). Before: `01-document-before.png`, `02-data-before.png`, `03-console-before.png`, `04-academy-before.png`. After: aligned document page, native reading table/formula, mobile entry, education and work surfaces. These are actual app captures, not generated mockups.

## Long-document performance

Chrome 154.0.8037.92, three baseline and three current runs, 300 blocks, 696,055 characters, 2,102,269 fixture bytes. Same loopback preview, viewport and scripted input; no regression or soak ran concurrently with this benchmark.

| Median across three runs | f6b02a4 | Current |
| --- | ---: | ---: |
| Document ready | 265.2 ms | 284.3 ms |
| Input-to-double-RAF P95 | 32.1 ms | 31.7 ms |
| Sampled JS heap | 6.86 MiB | 8.42 MiB |
| Tasks > 50 ms | 0 | 0 |

New functionality adds a modest loading/heap cost while maintaining the input paint budget. The double-RAF metric is a paint proxy, not complete INP. Sampled heap is not process RSS or a multi-day browser leak test. Performance report: `output/document-studio-20261003/performance/result.json` (ignored).

## Sustained collaboration acceptance

The harness owns a model-free loopback preview, its synthetic database and twelve independently authenticated HTTP/SSE clients. It exercises concurrent different-block rich writes, exact returned transaction values, version-monotonic events, forced reconnect with Last-Event-ID, ongoing/final value integrity and a revoked-identity 403 probe. Progress is atomic JSON without invites/cookies. The harness records source hashes and rejects monitoring gaps exceeding 90 seconds at the planned 30-second write interval, so sleeping the host cannot turn elapsed calendar time into a successful continuous run.

Completed smoke: 122.78 seconds, twelve editors, 896 writes, 1,846 document events, 1,838 cursor events, 108 forced reconnects, 102 integrity checks, zero errors, final value/revocation pass, HTTP P95 469 ms, database 978,944 bytes. This is a short smoke, not multi-day acceptance. The first harness attempt exposed an observation race: a GET snapshot could precede a concurrently completed write counter. Final values were correct. Capturing pre-request counters and accepting only the corresponding monotonic interval fixed the harness; product data loss was not inferred.

After adding continuous-coverage monitoring, a fresh smoke passed in 12.44 seconds: 54 writes, 87 document/cursor events each, 48 reconnects, seven integrity checks, maximum monitor gap 1.89 seconds and no errors. The backend fingerprints match the longer smoke.

48-hour real-time run **started and is running**, not yet accepted. Start: **2026-10-03 07:48:28 UTC / 15:48:28 Asia/Shanghai**; target 172,800 seconds, twelve editors, 30-second writes, 300-second reconnects, owned port 18915. Supervisor process reported in progress is 30708 (venv launcher 57376); owned preview process 50084. Initial progress has actual writes/document/cursor events and zero errors. Completion is expected no earlier than October 5 at the same time, and requires continuous coverage, no errors and final revocation/integrity checks.

Progress: `output/document-soak-20261003/progress.json` (ignored). Hourly thread follow-up **“文档48小时协作验收”**, automation id 48, reports meaningful failure/completion and records the actual verdict. The 12 API actors are not 12 physical devices or a multi-day browser/UI memory test. Do not alter or fabricate its final result during handoff.

## Human screen-reader protocol

NVDA was not found in standard install directories; system-level reader interaction is unavailable in the current tooling. No spoken NVDA/Narrator result is claimed. Use the [official NVDA user guide](https://download.nvaccess.org/documentation/userGuide.html) for an assisted acceptance:

1. With NVDA running, open the isolated demo and use Tab/Shift+Tab through navigation, document options, formatting and block menus. Confirm labels, visible focus and no trap; Escape closes dialogs and focus returns usefully.
2. Enter reading preview. Use heading navigation and continuous reading through the entire document, including initially offscreen content. Confirm one document title and ordered section headings, without repeated autosave/connection announcements.
3. Navigate the table with T and Ctrl+Alt+arrow. Confirm column context and results; return to editing, focus a named cell and edit/format it with the keyboard.
4. Inspect the mathematical fraction using the reader's configured math support. Record actual spoken output and plugin/browser/version; MathML presence alone is insufficient. Confirm the caption supplies an understandable explanation.
5. Open collaboration/drawing/link dialogs, cancel and resume typing. For drawing, use coordinate inputs, confirm the saved caption and undo. Revoke a second test identity and verify its read-only transition and denial announcement.

## Current assessment and limits

Subjective frontend score: **89/100**, on the local personal/work product scale previously used (86/100). Typography and document appearance, cross-block operations, rich table/math and precise saved-version collaboration are materially improved. It is not an independent usability score or enterprise readiness certification.

Remaining work: table merge/split cells and arbitrary multi-cell replacements; inline equations; spreadsheet parity; complete lossless Markdown interchange (JSON preserves supported structure); CRDT/per-keystroke shared editing and live cursors on diverging unsaved drafts; SSO/cloud Feishu ACL parity; actual screen-reader speech; physical multi-device and multi-day browser memory acceptance. Existing limits remain 300 blocks, 8 MB per document, bounded undo and the last 50 merge baselines.

## Reproduction

Use `clawos/.venv/Scripts/python.exe clawos/scripts/run_regression.py` for the full isolated regression; do not run tool tests against the everyday database. Use `node --test clawos/tests/*.test.cjs` for Node regression. Start `learning_preview.py` with a distinct session and loopback port; both browser scripts verify its isolation marker before synthetic writes.

Run `document_studio_acceptance.cjs` with `--url`, `--playwright`, `--browser`, `--axe`, `--out`. Run `editor_experience_benchmark.cjs` with the same paths and `--baseline f6b02a4`. Bundled Playwright and the existing Chrome installation were used; axe was installed only under ignored output.

Run `document_collaboration_soak.py --hours 48 --workers 12 --interval 30 --reconnect-seconds 300 --port 18915 --session document-soak-20261003 --out clawos/output/document-soak-20261003`. It terminates only the preview it created. Progress/source hashes and actual final results determine the verdict; no simulated duration replaces the wall-clock test.

Delivery follows the user's explicit authorization for `Snape-arch/agent`, branch `codex/coding-agent-competitive-p0-p2`. No master integration or force push. Exclude `tools`, weights, secrets, databases and runtime output; preserve the pre-existing `clawos/skills/skill_registry.jsonl` modification.

## Actual 48-hour attempt: failed continuous coverage (2026-10-03)

This supersedes earlier running / pending descriptions. The target was **172800 seconds**, with **12 authenticated API clients**. Start **2026-10-03T07:48:28.659742Z**, finish **2026-10-03T12:40:35.558767Z**. Reported elapsed **17526.89 seconds (4.8686 hours)** includes a **5453.69-second observation gap** and is **not successful continuous load**. The >90-second coverage guard failed honestly; host sleep/suspension or scheduling blockage is possible, but the report alone does not establish its cause.

- Verdict **FAILED**; **14 errors**: 12 stream ReadTimeout events, one writer ReadTimeout, one continuous_coverage / monitor_gap_5453.7s event.
- **4795 writes**, **47309 document events**, **214833 cursor events**, **480 controlled reconnects**, **1197 integrity checks**; sampled HTTP P95 **266.0ms**, database **1433600 bytes**.
- Per-editor acknowledged writes **[400,400,400,400,400,400,399,400,400,399,398,399]**. Shutdown code fetched the final document and compared all 12 blocks against those acknowledgements; the complete 14-error list contains **no final_integrity loss error**. This is an end-of-attempt value check, not proof of 48-hour integrity.
- Final authenticated revoke probe **revocation_pass=true** (HTTP403). The supervisor **30708** and its owned preview **50084** have ended; they were not restarted, and production was not restarted. The final report timestamp was checked against the owned process IDs.
- Evidence: ignored output/document-soak-20261003/progress.json; SHA-256 **e93dc701fae8a63fe01a7435838cc875f5091a6ab30afd006523c28863e1cabf**. All five recorded collaboration-core fingerprints were compared to current files and still match:

| Source | SHA-256 |
|---|---|
| services/academy_documents.py | c6aafcfa923b8e32a26a5f1c2581e590c882d70feef278b7970f9ee9bd89a5f8 |
| services/document_events.py | 7e796ce5b7242f1c4cde2ca8a52f764a1fbb87d1aaa80000cf87d42ea2c081c3 |
| services/document_cursor.py | 68af53fa3669b587395437a83646ffd51e8554c3449fa0f4539bb350aeff4f39 |
| services/document_merge.py | 7c27ef387df2b617c4c2ce6fcacf5a79a8e5544b7d0ed405d29a755fa97dd154 |
| services/collaboration.py | edbdc70c84f8a271d4bb7af726f7dc67baa03e56cedf3ae013338bcbe7366e36 |

This was API/SSE load on one host. It does not establish physical multi-device, real browser collaboration, screen-reader speech, or sustained browser memory quality. Failure is preserved; there is no new 48-hour start and no completed 48-hour claim. A retry needs an environment that maintains actual continuous execution; idle or suspended time cannot count. After the final failed conclusion is committed and pushed, stop heartbeat48 for this completed attempt.
