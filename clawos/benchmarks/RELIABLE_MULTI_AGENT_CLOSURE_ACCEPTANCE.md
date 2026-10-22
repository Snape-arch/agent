# Reliable collaboration handoff closure — 2026-10-05–06

Continues `63319b1`. Previous mechanism and negative live records remain in [phase-one acceptance](RELIABLE_MULTI_AGENT_ACCEPTANCE.md). This phase closes **execution → integration/test → separate model review → fresh patch replay/test → immutable handoff → exact packet acknowledgment**. Acknowledgment is not an application, merge, source commit or remote push. Source application requires its own reviewed action; dirty caller content must not be silently included in a task branch merge.

## Implementation

- `CollaborationDelivery` permits only passed runs with successful integration tests and an approved review without risks. Before preparing, reading or acknowledging a packet it verifies original source state, immutable baseline, accepted worker HEADs/differences, integration difference, captured answer receipts and frozen packet/worktree evidence. Source/index/draft drift rejects handoff without overwriting anything.
- The task-only difference is replayed using a **byte pipe** and Git `apply --index --check`/`apply --index` in a new worktree based on the captured baseline. Created files are staged through the replay; only authorized ordinary text files with Git mode `100644` are exportable. Existing executable-mode files (`100755`), deletes, links, submodules and mode changes are blocked. A caller's dirty baseline is explicitly identified in the manifest; its unrelated draft is excluded from the exported difference.
- The original caller-selected commands run again. Failed fresh tests and test-induced source/index changes block preparation while preserving the original run verdict and the failed delivery attempt. Three replay attempts are allowed; their wall time, including intervals abandoned by process death, is charged to the existing cumulative run wall budget. No additional model calls are needed for handoff.
- Each packet freezes `changes.patch` and `manifest.json` with the patch SHA256 and manifest digest, source/baseline/integrated/replayed commits, exact commands, fresh results, review and model-receipt evidence digest. Reading/acknowledgment rechecks the accepted difference and clean replayed HEAD. Idempotent preparation and acknowledgment still reverify evidence.
- The same kernel-held coordinator lock covers execution, replay and acknowledgment. Cancellation drains owned native writes/tests before releasing ownership, including repeated cancellation. Actual process death is detected as interrupted delivery work; the next explicit preparation uses a fresh worktree and retains the original attempt. The approved receipt is immutable and recoverable if a process exits between writing it and updating the checkpoint.
- Acknowledgment requires `confirmed=true`, the frozen owner label and the exact `manifest_digest`; stale packets, wrong labels and missing confirmation fail. Existing local-owner HTTP middleware remains responsible for access control. The label and packet digest are **not** organization identity, independently authenticated human review or an external attestation.
- Actual malformed worker, conflict or integration-repair JSON now receives at most one additional model format-repair request per proposal, using its captured public answer and parser error within the same scope/budget. The original answer/failed event remain. Repaired output still passes strict JSON, allowed paths, operations and Python syntax; no local guessed repair or Python-literal fallback is accepted. No-op proposals are rejected before writing. Each of the two integration repair rounds permits two proposal attempts, feeding back the rejected proposal and precise failure without resetting the shared model/token/wall budget.
- Planning/worker instructions preserve interface coercion, output-container and import contracts. Repair requests address all supplied diagnostics. The live pipeline's harness collects module failures in seven independently reported tests, including the original edge cases, rather than hiding remaining failures behind one fail-fast assertion. These tests are outside worker scope. The request-overlap metric ends requests at captured answers, including malformed answers and their format requests, to avoid counting an already-ended request as concurrent.
- Ready, failed, interrupted and acknowledged delivery states are synchronized back to the existing persistent task record, including exact packet identity and attempts. The primary execution verdict is retained; fresh handoff failures do not rewrite it into a false execution failure or an approved handoff.
- A failed real traceback can invoke a **deterministic AST repair** for missing local module namespaces. Its exact authorized file/line/name must match an unbound load in the current syntax tree. Only authorized root-level Python modules exporting the referenced functions are eligible; names bound anywhere in the file, unknown packages and unrelated names are excluded. Module docstrings/future imports are preserved; compilation, commit scope and subsequent caller tests still gate success. Events explicitly say `model_generated=false`. This supplies mechanical wiring, not semantic task logic, and is not attributed to the model. Other errors retain bounded model repair or fail closed.
- Windows case aliases, sensitive path aliases, reserved devices, trailing-dot/space and invalid/control characters are rejected before collaboration reads. This is path validation, not OS filesystem isolation.

## API and tool flow

1. Execute/resume `POST /api/subagents/run` with `team_profile="reliable_coding"` as in phase one.
2. `POST /api/subagents/collaboration/{run_id}/delivery` with `{"confirmed":true}` prepares the concrete packet and returns its manifest/digest/patch path.
3. `GET /api/subagents/collaboration/{run_id}/delivery` returns verified evidence and the task-only difference. A busy owner or stale/corrupted packet is rejected.
4. `POST /api/subagents/collaboration/{run_id}/delivery/approve` with `{"confirmed":true,"actor":"<frozen-owner>","manifest_digest":"<reviewed-digest>"}` acknowledges that exact packet. The source remains unchanged and the response retains `source_application_required=true`.

The existing `autonomous_subagents` tool routes `action=prepare_delivery`, `inspect_delivery`, `approve_delivery` with `run_id`; default `action=run` preserves prior behavior. HTTP handlers and tool routing are tested separately. No new graphical workbench, background scheduler, distributed lease or automatic branch application is claimed.

Progress and delivery operations remain available without an initialized model provider. New execution still requires one. The tool handoff path does not construct a provider or read its credential configuration; the frozen packet needs no additional model request.

## Verification

| Regression | Result | Evidence |
| --- | --- | --- |
| Final serial isolated full Python regression | **853/853**, 1,124.317 s, zero failures/errors | `output/regression/0564c65a7e6c46b9ab4d9b4a45353ec4`, `output/collaboration-delivery-final-full-regression.log` |
| Focused mechanism/entry regression before the final AST addition | **27/27**, 281.370 s | `output/regression/60445d7ed534467c94809d33e8e028f0` |
| Actual-traceback AST repair and rejection of unrelated/unknown names | **2/2**, 18.404 s | `output/collaboration-delivery-import-repair.log`; also included in final full regression |
| Handoff/cancellation/process-death/real SQLite task-record tests | **13/13**, 353.340 s | `output/regression/82838751ea4a4bb492bb5c39db3d6319`; also included in final full regression |
| Last offline-model factory and actual ASGI handler flow | **1/1**, 34.771 s | `output/collaboration-delivery-final-offline.log` |
| Last tool entry: no provider construction for handoff; legacy/run preserved | **3/3**, 0.234 s | `output/regression/f92a23d293914100a7000a7d47721b31` |

The full 853-test discovery preceded the final offline API/tool factory adjustment and its new fourteenth handoff test. Those final lines passed the separate offline 1/1 and entry 3/3 checks. No single 854-test full run is claimed. An earlier 848-test revision passed in 1,148.962 s before further live counterexample fixes; it is not final-source evidence. Existing SWIG/openpyxl deprecation and asyncio debug slow-callback warnings were non-blocking. Final Python compilation, function-JSON parsing and Git whitespace checks passed; no JavaScript changes or new browser/accessibility acceptance occurred.

The following three **real local Qwen** outcomes use identical unchanged collaboration/delivery services and acceptance harness:

| Live case | Result | Protocol wall time | Actual calls / charged tokens | Evidence under ignored `output/` |
| --- | --- | --- | --- | --- |
| Four-module CSV pipeline and fresh handoff replay | **PASS** | 242.422 s | 8 / 6,036 | `collaboration-delivery-final-pipeline-v3-20261005/report.json` |
| Real worker process exit, verified commit reuse, fresh interrupted attempt and handoff replay | **PASS** | 158.250 s | 6 / 2,673 | `collaboration-delivery-final-recovery-20261005/report.json` |
| Actual overlapping Git conflict, model resolution and handoff replay | **PASS** | 80.813 s | 5 / 1,806 | `collaboration-delivery-final-conflict-20261005/report.json` |

Each case records peak **two overlapping worker requests**, successful original and freshly replayed caller tests, model-review approval, preserved source and exact packet acknowledgment. Pipeline diagnostics identified missing local namespace imports and recorded **one deterministic AST coordinator repair**, explicitly not a model-generated correction; all seven independent module/composition tests then passed and passed again in the delivery workspace. Recovery actually exited with code 17 after saving addition commit `f7e4b836a29eaa112a822b9ca258bee09660b627`, reused that exact commit and retried interrupted work. The conflict case records one actual three-way resolution and five independent label assertions. These are three short single-host synthetic cases, not a large-corpus success rate or multi-day load.

Packet acknowledgment in the harness uses a synthetic owner label and explicitly records `actual_human_approval=false`. It does not substitute for a real person's release decision. All reports capture actual configured Qwen responses; deterministic fixtures alone do not establish live-model acceptance. The first three developmental pipeline attempts failed on JSON or actual integrated tests (196.984, 207.125, 260.421 s) and were additionally source-unstable. Two later source-stable versions still failed due to ineffective repair proposals (282.828 and 280.437 s). Their original failed verdicts/receipts remain. They are not counted as passes or overwritten by the final result. The first delivery regression also failed on Windows text-pipe newline conversion (9 tests, 105.210 s); byte-pipe replay fixed that cause. Subsequent nine-test and twelve-test intermediate regressions passed, followed by final handoff tests below.

Live-run captured source witnesses (the CLI does not import the server module):

| Source | SHA256 |
| --- | --- |
| `services/reliable_collaboration.py` | `705bd78e550cfe09d97d15da2e4601c9ccb78c3e16c72aa6cb7bf592f61e03a4` |
| `services/collaboration_delivery.py` | `a9c33a3f68c9f50a4a558185f8ee59b5e5362057ff6b3a68a7d9b56dae242ab5` |
| `services/autonomous_subagent_service.py` (unchanged this phase) | `fa4299e081ec404bb3d8336a08e119be059817828c8aebf4d87ee0391cbdded0` |
| `clawos_server.py` on disk during the live runs, before final offline factory guard | `9e5f7a7624462efe834df4d406e8f1e426e60b2bd7a0805be3e7225bbe1f2546` |
| `scripts/reliable_collaboration_acceptance.py` | `7b6eaf70932c40dc0ef2d30c663c136f5d88521e6bac8479b0d7d2adb9ce83c2` |

The later server guard is `a1d9b34cabd51152011b6468a46bf4adc77c1f8f834442e05f392dca878da0a4`, independently verified by the offline test using the real factory/handlers. The actual collaboration/delivery/acceptance code did not change after the three live runs; the CLI's historical server witness is preserved rather than rewriting those reports.

Pipeline report SHA256 `f1a3614046a5fd78a9da73a649f9d50e35dbeaccfd38cf09e9dad04e9332ed98`; recovery `4fafcd262a9a2a1268fcc963448a4f87c166579d744d46468c32a1ebf36dc91a`; conflict `c237dcf8a49641cbb16fd7aad1b2d31b019c296b1c83ed83987a0dd1e1f3311d`. Final nine modified/new source/schema/test files are listed in ignored `output/collaboration-delivery-source-fingerprints.json`, canonical sorted-key path/hash JSON bundle **`046aa3d1aee7ddaf68ef660499a0ceb037c36a7199f3adc8c17619e72c1ab103`**. Handoff documents are outside that bundle.

The owned existing llama-server/Qwen3.5-9B-Q4_K_M process on loopback 18927 (two slots, context 8192, GPU layers 20, PID 63900) was closed after checking exact executable/start UTC identity. Only existing executable/weights were read; production and unrelated previews were not restarted. Replayed tests reported Windows Job Object process/memory constraints, but low-integrity workspace labeling failed; filesystem isolation, non-bypass direct socket isolation and `production_sandbox_ready` were false. An authenticated default-deny external proxy was enabled. These are the observed boundaries, not strict-sandbox acceptance. Everyday DB SHA256 remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`.

Reproduction uses an existing explicit loopback provider without loading environment credentials:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_regression.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/reliable_collaboration_acceptance.py --live --url http://127.0.0.1:18927/v1 --scenario pipeline --exercise-delivery --out clawos/output/collaboration-pipeline
.\clawos\.venv\Scripts\python.exe clawos/scripts/reliable_collaboration_acceptance.py --live --url http://127.0.0.1:18927/v1 --exercise-recovery --exercise-delivery --out clawos/output/collaboration-recovery-delivery
```

The pipeline covers four modules (CSV parsing/composition, validation/cleaning, grouping and Unicode JSON rendering), input preservation, finite/nonnegative numeric validation, missing values, sorting/grouping and an empty report. Harness-authored assertions are outside worker write scopes. The model determines the dependency graph. It remains a synthetic repository, not a large public-project benchmark. Loopback model output uses the configured real Qwen; fixture regressions alone do not establish that outcome.

## Limits

Single-host bounded collaboration and exact handoff evidence are accepted only to the extent of final results below. A successful small pipeline does not establish task success rates, multi-device/multi-day load, distributed fault tolerance, independent judge quality or parity with Claude Code/Codex. Harness packet acknowledgment is synthetic, not actual human approval. Replay inherits the current sandbox and exposes its real result; process/memory-limited compatibility execution is not strict filesystem/non-bypass network isolation. No host isolation configuration, production process or unrelated preview is changed. Existing document 48-hour failure remains a failure.

Delivery patches target the captured baseline and need separate review before application. The complete worktree branch may contain caller dirty snapshot content; do not equate its full branch diff with the exported task-only patch. Protected evidence detects accidental drift/tampering relative to checkpoints; a host owner capable of rewriting code/checkpoints/evidence is outside this trust boundary. Native Git verification is synchronous when using the Python API; HTTP inspection/acknowledgment uses a worker thread and can take noticeable time on Windows.

Commit/push use the user's authorized `Snape-arch/agent` branch `codex/coding-agent-competitive-p0-p2`. Only related source/tests/handoff documentation are included. `tools`, weights, credentials, databases, output and the pre-existing skill-registry edit are excluded; no force push or master merge.
