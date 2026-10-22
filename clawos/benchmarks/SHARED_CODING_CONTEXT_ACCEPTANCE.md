# Shared execution context — 2026-10-07

Stage 3 of the ordered coding-capability plan, continuing `5af67b65430a7d2a392002a6c5b1b8c8526af035`. The shared-context implementation is complete; real-model task acceptance failed in both execution modes. Software regression and live task success are reported separately.

## What changed

`CodingContextService.build_execution` delegates to a shared `CodingExecutionContext` builder. Both the single-agent proposal loop and iterative agent, and the reliable collaboration planner/workers/diagnostician/repairer/conflict resolver/reviewer, consume this versioned structured source view. Generic IDE inspection and existing repository-wide intelligence retain `build`; those broader APIs are not claimed to inherit this execution read policy.

The view carries writable paths, read-only source evidence, raw byte SHA-256, source fingerprint, Git revision, line spans, bounded symbols/import facts, applicable ancestor instruction files and failure-frame provenance. Python local imports resolve relative packages and at most two dependency hops. Equal bytes, revision, objective, scope and budget produce equal views across checkout locations; absolute workspace locations, branch names and cache-hit counters do not enter the digest. Different scopes or dependency commits legitimately produce different views. This is static import evidence, not uniform LSP call-graph coverage or complete repository analysis.

Instruction hierarchy reads are capped at 12 files and included in the total source-byte budget. The preserved original objective is passed outside the bounded context excerpt; single proposals return its SHA-256. Target function excerpts take precedence over earlier exception classes, and budget trimming retains partial source text when it fits.

Default rendering is bounded to 6,000 serialized characters, with whole structured fields reduced before serialization; it never slices the JSON packet. Each source file is at most 128 KB, source bytes total at most 384 KB, writable paths at most 24 and source rows at most 40. Unreadable implicit dependencies are reported as omissions; declared paths fail closed. Instructions are repository input, never higher-priority system instructions. No caller-supplied diagnostic is relabeled as an actual executed test frame.

For single agents, explicit file/directory focus determines the write scope; directory expansion over 24 source files is rejected. With no focus, a bounded path-token ranking chooses up to 12 code files. This does not provide full symbol search in large repositories: callers should narrow the task. New proposed paths must be declared explicitly. Dependencies are read-only even if the model asks to edit them. Iterative read/search/symbol observations use the selected view rather than unrestricted recursive traversal; observations are bounded, source drift is rejected before requests/patch planning, and evidence refreshes after each edit attempt. Initial optional LSP evidence is invalidated after an edit attempt.

The source-path policy excludes runtime/weight directories, credential-like JSON/YAML/TOML/TXT filenames, unsupported types, devices/aliases and links/junctions. It is not proof that permitted source text contains no embedded secret and is not an OS read, write or network boundary. Prompt withholding does not provide adversarial hidden-test confidentiality. The prior `production_sandbox_ready=false` evidence remains unchanged.

Collaboration also retains its existing authorized full-file packet fields alongside the shared view; complete prompt payloads differ from single-agent payloads. The parity test concerns the structured shared view on equal snapshots/scopes, not identical full prompts. Collaboration records immutable context JSON under the owned run, links model starts and normalized answer receipts to exact context digests, checks packet/receipt integrity during recovery and delivery, and freezes the records in the delivery manifest. Unfinished new runs reject changed context-builder/analyzer policy fingerprints. Explicitly recovered old runs without a context policy retain their original packet protocol. Receipt checks are integrity checks in a trusted coordinator, not cryptographic provider or model attestation. Different failed attempts retain their own evidence.

Failure frames now reject impossible line numbers and restrict module-level called-symbol extraction to the displayed failure span. The same actual-frame extractor supplies single-agent repair context and collaboration diagnostic/declared-rule repair context.

## Verification

Initial focused mechanism suite: **9/9, 35.677 seconds**. An intermediate focused suite after read-policy and receipt error handling: **9/9, 34.654 seconds**, `output/regression/2ec31e26fa94485490581308e00488e9`. Tests exercise package imports, scope/instruction resolution, exact same-snapshot parity across checkout locations and between single/worker model inputs, bounded packets, path/link denial, source/missing-file drift, real failing-frame extraction, read-only write rejection, context tampering at delivery and policy drift on recovery. Link denial uses a mocked filesystem flag, not OS sandbox acceptance. Model replies use fixtures and commands use native owned processes.

Existing iterative single-agent suite: **6/6, 11.424 seconds**, `output/regression/50bb96976c0045238a5234d64ee7e57b`; this preceded later receipt/default-selection refinements and is not final full-source acceptance.

A refinement suite initially failed **12 tests, 39.958 s (one failure, one error)**, `output/shared-context-focused-v2-20261007.log`: the objective hash was added to a hook but omitted from the returned proposal, and a fixture demanded retained code under a budget already exhausted by metadata. The return field was connected; the partial-fit fixture now measures an actual smaller-than-full packet budget and still requires a nonempty shortened dependency excerpt. No source-budget or write gate was relaxed. Final focused **12/12, 40.203 s**, `output/regression/be797adb91cc40c18825a3265a158fde`, adds function/class selection, partial-fit trimming, long-failing-function assertion windows, missing artifacts and full long-objective preservation.

The first full regression (`output/shared-context-full-20261007.log`, root `5f4e97c27b564c5b841149f8d7dcd5ee`) and first live project attempt (`output/shared-context-project-live-20261007/`) were deliberately interrupted after inspection exposed poor excerpt selection and whole-field removal. They have no final acceptance count or live PASS report and are not counted as successes or independent model task failures. Identity-checked owned processes and the original model helper were stopped; actual results are preserved in `output/shared-context-refinement-interruption-20261007.json` and the original helper stop record. Full regression restarted with final sources in `output/shared-context-full-v2-20261007.log`, root `c1fbe865e6e242ab96fc390ea44dae58`; live work uses a fresh output root and new helper start.

Final full isolated regression **878/878, 1,694.038 seconds**, root `output/regression/c1fbe865e6e242ab96fc390ea44dae58`, log `output/shared-context-full-v2-20261007.log`, passed with final frozen sources. Existing SWIG/FastAPI on-event deprecations, openpyxl column-heading warning and asyncio slow-callback diagnostics did not fail tests. Real-model project validation completed with two negative results below. The two live harnesses use explicit loopback Qwen, unchanged committed ClawOS Python snapshots and the previously exercised two-module task. Single-agent validation executes only caller-frozen commands on an owned worktree; model-selected commands are recorded but not executed. The collaboration harness permits fresh delivery replay only after integration passes; this negative run never reached replay. These differ in orchestration, calls, role scopes, format handling and approval protocol, so their wall times and pass results are not a controlled single/multi or model comparison.

### Final-source real-model negatives

Both harnesses seeded the same unchanged committed HEAD `5af67b65430a7d2a392002a6c5b1b8c8526af035`, **330 Python files / 4,579,839 bytes**; the selected business modules were the original unpatched files. No retry increased the original collaboration limits (24 calls / 50,000 tokens / 1,800 seconds), and no generated business changes were applied to the daily checkout.

| Run | Actual result | Duration | Calls / charged tokens |
| --- | --- | --- | --- |
| `output/shared-context-project-live-v2-20261007` | `test_failed` | 863.187 s harness / 856.234 s coordinator | 6 / 30,498 |
| `output/shared-context-single-live-20261007` | Invalid strict JSON; no patch applied | 84.906 s | 1 / 2,547 |

Multi-agent: two dynamic tasks, peak 2 actual worker requests, both worker commits retained. One history answer required an actual JSON format repair. The original public suite then had one error in 4 methods: invalid `max_messages` raised `TypeError` where the frozen test requires `ValueError`; all 10 document compatibility methods passed. The model diagnostician received actual frames, but its requested targets included the already passing merge module. Its repair response had identical old/new text and was rejected; the next repair attempt was denied before a model call because conservative token admission would exceed the unchanged 50,000-token budget (the ledger ultimately charged 30,498 actual tokens). This is an admission-boundary failure, not a report that 50,000 actual tokens were consumed. Shared evidence alongside retained legacy source fields adds prompt overhead; avoiding duplication and measuring tokenizer cost remain explicit follow-up work rather than relaxing the budget here. No reviewer, successful integration, fresh delivery or post-check execution followed. The vacuously true report field `repeated_death_recovery` does not count as recovery evidence: `crashes=[]`, no failure injection in this run.

There are **4 immutable contexts / 6 answer receipts**, each linked to a known context; a separate final-code `verify_receipts` inspection passed. The harness's `execution_context_bound=false` is its final-delivery predicate; delivery was never reached, so artifact integrity is not presented as successful delivery. Model-answer and context integrity checks cannot fix poor model edits or make failed tests pass. Multi report SHA-256 `4ed398257e2b3ace7b47526ecff0e6a00a9ce32067813f7c37f6945435eed7f5`.

Single-agent: complete stop answer (2,189 prompt + 358 completion tokens) was malformed JSON and omitted the second requested change. It was rejected before planning/applying; original snapshot and framework sources remained intact. No caller test or post-check ran. `shared_context=false` in the harness is based on a returned proposal, which never existed; the model request did use the shared-context path but that is not successful proposal acceptance. Single report SHA-256 `9c8235863ca616174d67cfa77443cf3ec2d42613f43d07b3c83d32201716cdc3`.

These final-source failures remain negative, not two independent benchmark resolution-rate samples. They show the format, semantic repair and prompt-cost limitations of this local model. They do not establish equal capability, quality improvement or a pass-rate improvement from the context refactor.

The eight internal post-check methods remain prior diagnostic/held-out cases, not a newly independent blinded corpus. No post-check result is fed back into the model in the same run. Earlier stage-1 negative reports remain negative. No source application of generated business-module patches or human release approval is included.

Legacy stage-1 delivery `collab-ae865c886a9f47feaeeead72a0adf764` was inspected with the final code without executing a new model request or applying changes. Its original context-less manifest remains valid and `ready`, digest `4e10831b1cfd7df8fc5924f5a62059e88cd389a12ea1d035cef012e9f1535375`. This verifies inspection compatibility, not new process-death recovery.

## Frozen source witness

Final 10 changed Python source/test files have bundle SHA-256 `dfb0cc603cf3f1b70cec2ec34128e3656d18697642d62133a3ed8282fd0450b6`. Live reports separately witness their loaded service/harness files, including unchanged workflow/sandbox modules; these bundles cover different sets and must not be equated. Canonical sorted compact JSON of each report witness map hashes to `c68c4ade0bb6e689c17882c381f5317ec628f3414791220b928b6625371df59d` (multi, 10 files) and `9a408d68c4214f26513438b31e5115359c391efef4ce3b4378f2abc2e87a0edc` (single, 11 files).

| File | SHA-256 |
| --- | --- |
| `clawos/scripts/collaboration_project_acceptance.py` | `60a9ebc565d7fcbea107f1e422b4fece6403b360dffa3a632f1d0cb792e9b8d1` |
| `clawos/scripts/shared_context_single_acceptance.py` | `2cd69fe03664dfdbc4c1d47778bb3a6d01b56835d3a122ab4e7db8acb2323e31` |
| `clawos/services/agentic_coding_loop_service.py` | `e428f94d890ea776539654f5b8b8b3faf0647aa40d7edcdef79d271ff08933bd` |
| `clawos/services/autonomous_coding_service.py` | `07c2a6d1345f193a30512eadf96d1a62453ae3b7c01e1518621573cd64ee175c` |
| `clawos/services/coding_context_service.py` | `419c1d29ae7ded07cac95bf4cecd6c5ab74a38e9e92c730c53f10bd469dd7d9f` |
| `clawos/services/coding_contracts.py` | `06df0d2264cbda5c0bf393736d6aca4e7b5a3eb1e6b04dd346b08e4a66629f61` |
| `clawos/services/coding_execution_context.py` | `4c9bc6b3ec34b809827b6e958d363bcb8528bd49a5e578549dbd9620e59e44eb` |
| `clawos/services/collaboration_delivery.py` | `546058a4dd7b613f0ef7a40ba5b22ac80c18f49fa77c2accc173222dd710bf17` |
| `clawos/services/reliable_collaboration.py` | `8a5b7a1e5a3c6d686466e86da52c2a324a5865ac9abc5e97ec9b70796d8cd51d` |
| `clawos/tests/test_coding_execution_context.py` | `1680f6dde5051443eabc0ab1c4c38b44c3fa625808a50d145705e88be81a81b3` |

## Workspace safeguards

All 10 frozen changed Python files compiled and remained byte-identical to the source witness. `git diff --check` passed (Git only reported configured LF/CRLF normalization notices). Daily database SHA-256 remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`; the original dirty skill registry is preserved and excluded. The final owned model helper PID 39816, port 18930, executable and UTC start `2026-10-07T06:06:21.0197081Z` were verified before stopping at `2026-10-07T06:26:08.7479345Z`. Production and the existing preview were not restarted. No output, weights, database or credential files are submitted.

## Remaining work

Same-task/budget comparison across models and execution modes, larger independent task sampling, dynamic strategy choice and verified failure admission into self-evolution remain later stages. Shared context alone does not establish improved resolution rate, production isolation, multi-host collaboration or sustained-load readiness.
