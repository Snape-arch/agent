# P0 deployment, business persistence and recovery faults (2026-10-23)

## Latest terminal evidence and follow-up

Source `de3b5149b99af5fa3d8d044c021c4bfc04a65adc` passed the fresh local frozen
full suite on the independent application interpreter: **1055/1055, zero skips**.
Module partitions 307/189/208/351 were complete and disjoint; individual durations
503.188/150.141/114.625/785.563 seconds. Source bytes and HEAD stayed unchanged;
daily DB stayed unchanged and the original registry bytes were restored.
Evidence: `output/p0-deployment-final-20261023/full-result.json`,
`full-source-audit.json`. These are deterministic tests, not real model quality or
continuous-load evidence; independent shard durations are not summed as load.

The same source's hosted run [39814970787](https://github.com/Snape-arch/agent/actions/runs/39814970787)
**failed**: three shards passed; shard 3 failed
`test_model_acceptance_text_output_includes_counts` (mock evaluator: one of two
tool cases failed, score 8/10). The original text lacked per-case reasons; its
root cause, including any suspected latency, is **not proved** by this annotation.
The required final gate correctly failed. Raw terminal and annotation receipts
are retained; local success is not substituted for this hosted failure.

Follow-up CLI diagnostics retain failed case/scenario/tool, measured time and
reasons without echoing tool payloads. Exit success now also requires the provider
and full evaluation to pass, closing the existing `ok=false`/exit-zero path.
The frozen benchmark thresholds and provider requirements are unchanged.
The expanded model-acceptance module passed 11/11 (4.473 seconds); diagnostic and
provider-failure negatives are included. This does not establish the old cloud
failure's cause or claim a new full-suite result.

An additional real CMD negative check found that nested batch failure exits could
stop startup yet return zero. A standalone failure label now returns one for all
main startup failures; helper subroutine return contracts are retained. Actual
unmarked/missing interpreter checks return one without starting services; the
default prepared-runtime selection returns zero. Deployment module 8/8 (0.657
seconds), plus the actual prepared default batch check, passed. These are changes
after the 1055-case frozen source and are validated separately until a new hosted
terminal gate completes.

Daily DB SHA-256 remains
`8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`;
original dirty registry SHA-256 remains
`a72423d78ff1e7d67c646fcd7debf1824ce9e88767b0034455ff1fefcc5a23d4`.

P0 is not wholly accepted. This block fixes the application dependency environment
and incomplete recovery activation; browser interaction, physical reboot/power-loss
durability and the 275 missing historical artifacts remain separate gaps.
`production_sandbox_ready=false` is unchanged.

## Implementation

- Windows x64 CPython 3.12 profile: 135 exact distributions with wheel SHA-256,
  explicit PyPI origin and transitive provenance. Preparation creates a new venv
  with `include-system-site-packages=false`, checks dependency conflicts, checks
  the entire distribution inventory/location, imports real native libraries and
  executes a CPU tensor operation. Failure preserves logs/state and the previous
  activation. LF/CRLF dependency inputs normalize to the same identity.
- `start_clawos.bat` selects the verified activation before starting services;
  verification failure stops startup. `--check-runtime` verifies the actual batch
  path without starting services or loading `.env`. Explicit `CLAWOS_PYTHON`
  remains a deliberate development override.
- Standard base CPython, LibreOffice/desktop tools, optional PaddleOCR and model
  weights remain external. This is an isolated venv, not a bundled portable
  interpreter or an attestation of every installed library byte. ASR imports do
  not certify recognition accuracy or provision its model weights.
- Recovery progress markers are written before copies. Database copy is now
  inside the error boundary; data/manifest/report writes are flushed, and JSON
  receipts publish atomically. Failed error-receipt writes preserve the original
  exception and pre-existing progress marker. Startup and health reject incomplete
  backup/recovery workspaces. No running user database is replaced.
- Knowledge create/update/delete embedding refresh and PDF upload parsing/indexing
  run in worker threads. Slow encoder regression proves unrelated HTTP reads can
  respond. Default numerical thread pools are bounded to two before imports;
  explicit operator settings are retained. This does not certify all CPU-heavy
  endpoints or multi-user load behavior.

## Evidence

Independent environment installed from the hash lock:
`output/app-runtimes/windows-py312-bb8d1b6c48bc-a2060ee0`.
Python 3.12.14; lock identity
`bb8d1b6c48bcf9b77ebfedb69db91cb4d0e51d3b474d38975a0a32a10e443a2a`.
`pip check` passed. Installation and receipts remain in ignored output; no package
binaries, model weights or private configuration are committed.

Targeted tests: application runtime 7/7 (0.053 s, including CRLF and tamper checks),
recovery 12/12 (3.582 s), HTTP responsiveness 2/2 (0.146 s). These are distinct runs,
not an aggregate model success rate or continuous load test.

Real storage-fault child processes on the deployment interpreter: 19/19 checks,
`output/recovery-faults/a39fc4a3633a46eda8a1afdf5ffb9f8d/report.json`.
Children exit 73 during partial database and partial source writes. Injected
ENOSPC/EACCES produce failures, no success report, and unusable workspace markers;
a fresh-directory retry succeeds. Source bundle and live fixture database remain
unchanged. Logical injection is not a physical disk-full device, physical power
cut, controller-cache or operating-system reboot test.

Full business terminal round: **32/32 passed**, 28.515 seconds,
`output/p0-business/f48cdf4357ea4d919675fcdc7208aac7/report.json`.
Two full application lifespans used the same prepared interpreter and actual
Chroma/Qwen embeddings. HTTP covers knowledge capture/search, exact PDF download
and citations, code/table/math notes and stale-write rejection, Markdown/PDF/JSON
report downloads, a real queued worker reaching `succeeded`, source search and
reading checkpoint, and source-bound textbook graph/route. A fresh process retained
notes, completed tasks, graph, reading position and download hashes. Health rejects
incomplete recovery, an exclusive bind proves port release, and the actual command
entry point rejects an incomplete workspace before creating its DB. Both owned
processes shut down normally. Synthetic inputs and zero generation calls remain
explicit; no browser, semantic-quality or multi-day result is claimed.

The actual batch `--check-runtime` command passed without starting services or
loading `.env`. Full-suite terminal results will be recorded after completion.

Historical artifact inventory remains 275 missing (11 reports/264 traces), zero
recorded expected hashes. A bounded inventory of existing backup/output trees
inspected 52,306 filenames and found eight same-name candidates, zero verified
identity matches. Tools/models/runtime packages were excluded. Same names are not
trusted restoration evidence. No references were deleted or relinked. Evidence:
`output/p0-deployment-20261022/missing-artifact-inventory.json`; daily DB unchanged.

## Retained failures and boundaries

- The initial restricted-executor recovery test could not create/clean temporary
  fixtures (24 errors); normal-user isolated rerun exposed a real Windows fsync
  handle-mode bug. That 12-error round is retained; writable handles on only new
  snapshot/recovery files fixed it. Final 12/12 passes separately.
- Business rounds `9a6ba822330449dc86b3af42802c5718`,
  `759abe9eaa1a45179c65fc5c1db3cdbe`,
  `164edc4becc8435181c66e3aa61d5884` each exceeded the original 180-second write
  budget and failed. No failed round is overwritten. Tracebacks placed lazy
  SciPy native import on the waiting thread; numerical thread limits alone did
  not fix the application-shaped case. A simple isolated Chroma-then-transformer
  import completed in 5.64 seconds. Replacing the probe's blocking stdin shutdown
  watcher with an owned stop file allowed the same business operations to finish.
  This supports a test-driver stdin/native-initialization interaction; the exact
  CRT/DLL internal lock has not been proved. It does not establish a three-minute
  product latency fix solely from numerical thread limits.
- Round `9983a8ffeda1437788681f56ea6eaaf6` passed 30 recorded business/restart
  checks but failed overall when a closed-loopback HTTP probe returned
  ConnectTimeout rather than ConnectError. The final probe requires a real
  exclusive bind after process exit; a timeout is never counted as closure.
- In-app browser navigation timed out and its ERR_EMPTY_RESPONSE internal page
  was rejected by Browser Use URL policy. No alternate browser/CDP/Playwright
  bypass was attempted. Browser interaction remains unverified; HTTP checks do
  not certify visual quality, keyboard behavior, accessibility or screen readers.
- Business inputs are explicitly synthetic and generation-model calls are zero.
  Actual Chroma/Qwen embedding use is verified separately from teaching/research
  semantics. Real model quality, independent teachers/learners, multi-device and
  multi-day load remain unproved. Daily DB, original registry and production
  processes are preserved; historical missing artifacts are not fabricated.
- Round `4a4de134147a4d4b9d89f2aad4a15bed` correctly rejected incomplete startup
  before opening the database, but the custom Uvicorn Server driver returned zero
  after a failed lifespan; its exit-code assertion failed. The final negative
  check uses the real `clawos_server.py` command entry point, rather than changing
  the expected exit to zero or weakening the application guard.
- The first local full-suite shard 1 failed the frozen code-statistics case at
  4185.289 ms against its unchanged 4000 ms limit. Default stats were reading
  backup files and unknown/binary extensions. Defaults now exclude backups/tools
  (case-insensitive) and unrecognized extensions, and skip symlinks; explicit
  text-extension opt-in remains available. Scope regression 1/1 passed and the
  frozen scenario module passed 7/7 (7.187 s) on a separate rerun. The ongoing first full
  suite predates this delta and is not the final frozen-source full-suite proof.
