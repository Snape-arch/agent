# Document Studio acceptance — 2026-10-03

## User clarification — 2026-10-30

The user states that they deliberately shut down the computer overnight because
of fan noise and instructs **no retest for now**. Record this as the user-provided
environmental interruption context; the raw timeout evidence and incomplete
48-hour acceptance remain unchanged. This attempt is not evidence establishing
a software defect. Reminder48 was deleted after the terminal documentation push;
do not restore it or start a replacement run without a new request.

## Terminal failure of frame-boundary 48-hour retry — verified 2026-10-30

**FAILED, not accepted as 48 hours.** Frozen source
`9bff1df718ec9d9f0a8fddd6e916589f77d41914`, 12 authenticated API/SSE clients,
target 172800s, `complete_frame_boundary`. Started 2026-10-29 05:30:38.491081Z;
finished 17:38:32.950667Z, last report update 17:38:33.100385Z (Beijing
October 30 01:38:33). Elevated host-side queries of recorded worker47628 and
preview5500 found both absent; report also records `preview_stopped=true`.
This conclusion does not rely on restricted process visibility. Neither service
was restarted, and no new round was started.

The retained last-live sample records **42036.954s (11h40m36.954s)** covered,
42036.757s wall and maximum observed check gap 11.641s against 30s allowed.
Calendar start-to-finish is 43674.459586s; **1637.702586s after the last live
wall sample are uncredited**, not successful load. The persisted live
`continuous_coverage_pass=true` is not a terminal continuity certificate.
The test did not complete final-value/count/version checks, all-12 SSE final
convergence or the four revocation checks: these fields are absent, **unverified**.

Report aggregates: **16671 writes, 162366 document events, 757236 cursor
events, 1677 controlled reconnects, 4136 integrity checks, 12 errors**.
All errors have ReadTimeout type (11 stream entries and writer4), around
43674.47–43674.61 elapsed seconds. Stored stream diagnostics include
ReadTimeout → ReadTimeout → TimeoutError → CancelledError, without sensitive
messages, headers or cookies; stream stages are 7 opening and 5 reading,
attempts around 140/141. Last frames are around elapsed42044–42046s. This
documents a stall/timeout; it does **not** establish Wi-Fi loss, host sleep,
server deadlock, or a shared root cause with earlier failures. The requests
targeted loopback; offline Internet alone is not an established explanation.

The retained per-client samples show 1388–1390 writes, 13498–13555 document
events, 63075–63108 cursor events and 139 reconnects each. Those samples
precede terminal errors; their write sum is16665 and live version16666, whereas
later aggregates/diagnostics advanced. They must not be represented as exact
terminal values or final convergence. Sample write ages4.579–30.079s and
stream ages0.047–0.625s also describe that earlier sample, not final health.

All **301 frozen source hashes and 542 snapshot hashes** still match. Saved
local1102/1102 zero-skip and all five successful GitHub40822184803 jobs were
rechecked against the frozen SHA; they remain prerequisite evidence, not proof
that this long test passed. The later research-subscription commit8bf9ecd is
outside the frozen snapshot and is not covered by this test.

Raw report SHA256:
`a6854330dd32656070032da2e70bc4701bb950a4d5a90e9de603da831d59d3f0`.
Ignored terminal audit: `output/p0-soak-retry-20261029/terminal-audit-20261030.json`;
original progress, source manifest, verified gate summary, launch ownership and
initial delivery audit are retained unchanged. Initial delivery audit described
the run while still running and is superseded for terminal status by this audit.
The October25 3-hour ReadError report retains SHA256
`203db7464c7b486d3be41cefa7a3d9f6e8e377cb9684c28f9583c1dfe1a464dc`;
the October29 high-frequency cancellation/stall failure is separately preserved.

This is a failed **single-machine API/SSE** run. Real browser/multi-device,
screen-reader, browser-memory and human teaching acceptance remain separate
and unverified. No paused/stalled/cleanup time or older run time is credited.
Only these acceptance documents are delivered; original registry changes,
credentials, DB, output, tools and weights are excluded. Reminder48 is removed
after the terminal documentation push is confirmed; failure does not authorize
an automatic replacement run.

## Verified full gate and fresh actual 48-hour run — 2026-10-29

Source **9bff1df718ec9d9f0a8fddd6e916589f77d41914** passed frozen local
**1102/1102, zero skips/failures/errors**. Shards 321/198/211/372 took
518.484/153.281/115.297/804.609s; whole run **808.688s**. All 465
source/dependency/fixture hashes and HEAD stayed stable, daily DB stayed
unchanged, and original dirty registry bytes were restored. All four Windows
jobs and the final gate in [GitHub run 40822184803](https://github.com/Snape-arch/agent/actions/runs/40822184803)
completed successfully, each checked against this source SHA. Evidence: ignored
`output/p0-soak-retry-20261029/{full-result,full-source-audit,cloud-terminal,verified-final-summary}.json`.

The independent snapshot exports only committed code/static assets: 542 files
checked by SHA-256 and Git blob IDs; no local config, credentials, registry,
database or weights copied. Its real 12-client smoke passed: 36.156s credited,
149 writes, 377 document events, 85 cursor events, 382 reconnects, zero errors;
final convergence/revocation and owned-preview exit passed. Export manifest:
`output/p0-soak-retry-20261029/snapshot-manifest.json`.

The fresh **172800-second / 12-authenticated-client** API/SSE run started at
**2026-10-29T05:30:38.491081Z** (13:30:38 Beijing), with 30-second writer
intervals and 300-second complete-frame-boundary reconnects, maximum monitor
gap 30s. Status is **RUNNING, NOT ACCEPTED YET**. Earlier failures contribute
no runtime or counts. Progress:
`output/p0-soak-retry-20261029/snapshot/clawos/output/document-soak-48h-20261029/progress.json`.
Worker **47628** started 05:30:36.0505765Z; preview **5500** started
05:30:36.3995605Z, loopback port18921. PID21904 is only the venv launcher.
Host-side command/session/start-time ownership was verified in outer
`soak-owned-process.json`; restricted process visibility cannot prove exit.
Parse timestamps as UTC values or retain ISO JSON strings.

New heartbeat **48** checks quietly each hour, notifying only actionable failure
or genuine terminal results; delete after terminal reporting is pushed. Check
301 source hashes/542 snapshot files, both clocks, all 12 writers/streams,
safe exception diagnostics, final values/counts/versions, stream convergence
and four revocation probes. Any ReadError, timeout, premature EOF, denial or
non-monotonic event remains failure. Sleep/pause/cleanup/after-exit time earns
no load credit. October25 ReadError and October29 old-client stall remain
failed and unchanged; a common root cause is not established. This ongoing
single-host API/SSE run does not certify 48 hours, real browsers, physical
devices, screen readers, browser memory or learning effects. Production was
not restarted; other P0 exclusions remain open.

## Reconnect diagnosis and bounded mitigation — 2026-10-29

The October25 3-hour failure stays failed. Its lone `ReadError` has no saved
exception chain, so its OS error/cause cannot be reconstructed. It occurred near
a scheduled reconnect; this alone does not establish a transport or cancellation
root cause.

An instrumented original frozen4d1da82 client ran the real isolated API with
12 authenticated clients, 1s writer intervals and 1s reconnect intervals, targeting
180s. It did **not reproduce ReadError**: its diagnostic wrapper recorded
2016 actual cancellations and zero ReadErrors. Instead it failed
`continuous_coverage / stream_6_stalled` at166.81s, with 165.187s credited and
169.55s total: 692 writes,457 document events,48 cursor events,2016 reconnects.
This is a different observed failure, not a substitute explanation for October25.
Evidence: original snapshot's `output/diagnose-original-20261029-a/progress.json`
and main workspace `output/soak-diagnosis-20261029/original-client-diagnostics.json`.

The test harness now closes normal reconnects between **complete SSE frames**
instead of using `asyncio.wait_for` to cancel an in-flight read. Multiline data
is assembled before closing. Premature EOF, ReadError, ReadTimeout, denial and
non-monotonic versions still fail; no transient-read-error retry was added and
no coverage/final integrity rule was relaxed. A deterministic negative control
shows that cleanup converting CancelledError to ReadError escapes wait_for as
ReadError; this establishes a possible classification hazard, **not that the old
real failure followed that synthetic chain**.

Errors now capture bounded exception types/causes, errno/winerror/status codes
and basename/line/function stack locations, plus per-client attempt/phase/last
version. Messages, requests, headers, cookies, full file paths and locals are
excluded. Future real errors must retain this evidence and remain failures.

Validation: stream handling **8/8** (including a real loopback TCP premature-EOF
negative control), existing coverage guards **8/8**, realtime merging **10/10**.
New harness real12-client smoke with the same1s/1s settings passed:
**180.484s credited,182.86s total,739 writes,1881 document events,425 cursor
events,1891 controlled reconnects,112 integrity checks,0 errors**. Maximum
monitor gap1.937s (limit5s); sampled HTTP P95968ms. All12 final versions740,
acknowledged values/counts, final convergence and four revocation probes passed;
301 source fingerprints stayed stable and the owned preview exited.
Evidence: main workspace `output/diagnose-frame-boundary-20261029-a/progress.json`.
The original probe includes diagnostic wrapping; single runs are not a controlled
performance comparison or proof of general reliability improvement.

Only QA harness/test/docs changed, not production collaboration services. No
production restart or new48-hour run occurred at this diagnosis checkpoint.
The previous1094-test gate belongs to4d1da82 and cannot certify this increment;
the new full/cloud gate was pending then and is superseded by the section above.
The next long run needs a fresh start on the diagnosed source. This short API
smoke certifies neither48 hours nor browsers, physical devices, screen-reader
speech, browser memory or real learning benefit.

## Continuous-load evidence repair — 2026-10-25

The failed October 3 attempt below remains failed. The harness now records both
wall and monotonic intervals, rejects clock discontinuities and monitor gaps,
and checks every authenticated writer and stream for stalled activity. Failed
coverage cannot resume earning time. Setup and finalization do not earn load
time. Each client must have writes, document events and cursor events; aggregate
counters cannot conceal one idle client. Final document values, version/write
counts and all 12 stream versions must agree. Revocation probes an already-open
SSE connection and requires denial/closure plus HTTP 403 for read, write and
presence. Source fingerprints include 300 handler/service/script/frontend files
and must remain stable. Output/session reuse is refused; reports carry update
timestamps and owned process identifiers without session secrets.

On Windows an owned process-scoped execution request prevents automatic idle
sleep and is released on exit. It does not prevent explicit suspend, shutdown
or failure; any resulting observation gap still invalidates continuous coverage.
No power-plan settings or production processes were changed.

The final real API smoke used 12 authenticated clients, one-second writes,
10-second controlled reconnects, and a 122.4-second target. Actual covered load
was **122.734 seconds**; total including finalization **124.44 seconds**. Result:
**passed, 0 errors, 823 writes, 1739 document events, 1731 cursor events,
144 reconnects, 94 integrity checks**, sampled HTTP P95 **609ms**,
maximum monitor gap **1.735s** (allowed 5s). All 12 final stream versions were
**824**, and per-client writes matched the final acknowledged counters
**[69,69,69,69,69,69,68,69,69,68,68,67]**. Final value/version checks, all four
revocation checks and source stability passed; its owned preview exited.
Evidence: ignored `output/document-soak-smoke-20261025-b/progress.json`.
The earlier 180.297-second smoke is preserved separately and does not cover the
subsequent final-stream convergence addition.

Counterexample regression **8/8** and document merge/realtime regression **10/10**
passed. Simulated clock counterexamples validate only the fail-closed guard;
they never contribute runtime to real load. The full local/cloud gate and new
frozen-source attempt are recorded below.
No 48-hour, real browser, multi-device, screen-reader speech or browser-memory
acceptance is implied by this API smoke.

### Final source gate and actual 48-hour retry

Source **4d1da82e531f1b15b0783615bd835bdf1fabab9c** passed the frozen local
**1094/1094**, with **0 skipped/failures/errors**. Shards 321/198/211/364
completed in 641.672/179.781/124.141/960.625 seconds; whole run **963.921s**.
All 463 source/dependency/fixture fingerprints and HEAD stayed stable, the
daily database stayed unchanged, and the original dirty registry bytes were
restored. [GitHub run 40178461195](https://github.com/Snape-arch/agent/actions/runs/40178461195)
completed successfully for all four Windows shards and the final gate, each
verified against this source SHA. Evidence: ignored
`output/p0-soak-20261025/{full-result,full-source-audit,cloud-terminal,verified-final-summary}.json`.

Only committed code/static assets were exported to an isolated snapshot;
540 files were checked against their exported SHA-256 values. No local config,
credentials, database, registry or model weights were copied. The snapshot's
own 36.219-second, 12-client API smoke also passed, including stream convergence,
revocation and owned preview exit. Export manifest records the Git blob IDs and
commit. This lets subsequent main-workspace edits leave the running sample alone.

The actual new **172800-second / 12-client** attempt started
**2026-10-25T09:11:09.259952Z**, with 30-second writer intervals, 300-second
controlled reconnects and a **30-second maximum monitor gap**. It **FAILED** at
**2026-10-25T12:16:10.477154Z** (20:16 Beijing time), well short of 48 hours.
Progress:
`output/p0-soak-20261025/snapshot/clawos/output/document-soak-48h-20261025/progress.json`.
Ownership manifest records actual worker **62940** (created
09:11:06.7048032Z) and preview **45436** (09:11:07.0694766Z), loopback port18917.
PID37152 was the exited virtual-environment launcher, not the load worker.
New thread heartbeat **48** was created for hourly quiet checks; the earlier
reminder had already ceased to exist. Notify only on actionable failure or true
completion, and delete this reminder after the terminal conclusion is pushed.

#### Verified terminal failure (observed 2026-10-25T15:57Z)

Actual continuous load was **11100.531 seconds** (3h05m00.531s), wall-clock
coverage **11100.494s**, total including finalization **11101.2s**. Time after
the stopped run, including delayed heartbeat processing, earns no load credit.
The sole error was **stream-7 / ReadError at 11100.41s**. It is close to the
37th scheduled 300-second reconnect boundary (443 reconnects = 12×37−1), but
this coincidence and empty owned stderr/preview logs do not establish whether
the cause was transport, service failure or cancellation timing. The error was
not relabeled as a normal reconnect; no source repair or new run is claimed.

- 12 authenticated API clients; **4410 writes, 42802 document events,
  199763 cursor events, 443 controlled reconnects, 1095 integrity checks**.
- Maximum monitor gap **10.766s**, below the 30s limit; sampled HTTP P95
  **156ms**, database **1478656 bytes**. The short observed interval passed
  continuity checks, but did not meet the 172800-second target.
- Final acknowledged writes **[368,368,368,367,368,368,367,368,367,367,367,367]**
  matched all 12 final document values and their sum4410. Final version **4411**
  equaled 1+writes; all 12 event streams converged to4411. Per-client document,
  cursor and reconnect counters also matched the aggregate counts.
- All four terminal revocation checks passed: an already-open SSE stream was
  denied and closed, and subsequent read/write/presence each returned403.
- All **300 source fingerprints and 540 snapshot file hashes** still match
  frozen source **4d1da82e531f1b15b0783615bd835bdf1fabab9c**. Source-map SHA-256
  (sorted compact JSON) **0e7a6ee6a597329191cb452cef903c8aaefccfb929bffd133f1e29d3725f4a0f**;
  snapshot-manifest SHA-256 **0b4b2c27c7e58dbcfe69e33920e05cd947e20925326d2e3fc01b3777de4b2777**.
- Raw final progress SHA-256 **203db7464c7b486d3be41cefa7a3d9f6e8e377cb9684c28f9583c1dfe1a464dc**;
  the report's final update is **12:16:10.488870Z**. The actual host-side check
  at15:57Z confirmed both recorded owned processes (62940/45436) no longer exist.
  This is verified termination, unlike the earlier restricted-process lookup.

Evidence remains under ignored `output/p0-soak-20261025`: original progress,
`terminal-acceptance.json` and `terminal-owned-processes.json`. No production
restart or local data/registry modification occurred. This is a failed single-host
API/SSE soak; it does not certify 48-hour operation, real browsers, physical
multi-device collaboration, screen-reader speech, browser memory or learning
benefit. Preserve the earlier October3 failure and duplicate-attempt records.
Before another fresh attempt, capture the exception chain and reproduce the
reconnect/cancellation boundary without weakening integrity or coverage guards.
Delete heartbeat48 once this terminal conclusion has been committed and pushed.

Monitoring correction: a restricted-shell process lookup could not see these
host processes and was incorrectly interpreted as termination. A host-side
ownership query verified both still alive with matching start times, scripts
and session; progress had continued throughout. The original mistaken witness
is superseded by `output/p0-soak-20261025/process-visibility-correction.json`.
A redundant `-b` attempt was refused before document writes because port18917
served the original session; its failed report is preserved. It did not replace
or interrupt the original attempt. Future monitors must not infer termination
solely from a restricted `Get-Process` result.

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
