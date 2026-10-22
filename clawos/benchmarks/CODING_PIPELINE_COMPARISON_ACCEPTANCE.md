# Frozen coding pipeline comparison — 2026-10-07

Stage 4 follows `45927e2205fada3f37f8fab6737398b3f71ca645`. The user chose a local single/multi comparison with the existing Qwen3.5-9B model. A multi-model factory/CLI interface is implemented; no cross-model quality conclusion is claimed. The final live paired run and independent evidence audit completed; final isolated full regression passed 892/892.

## Protocol

`CodingComparisonService` freezes clean explicit source snapshots, complete original objectives, authorized paths, caller requirements and primary/post-validation commands before any model request. Plans include exact Git source/tree identities, source stamps, case and task-group digests, implementation witnesses, model configuration fingerprints, per-arm limits and the full run order. The CLI predeclares two repetitions: single→multi, then multi→single. Four arms are repeated measurements of **one reused internal task**, not four independent tasks. The CLI accepts up to four explicit credential-free loopback model entries; the service accepts explicit normalized provider factories. It does not load daily provider credentials.

Each arm has the same ceiling: **24 calls, 50,000 charged tokens, 1,800 seconds, 300 seconds per request/command, 1,800 output tokens, three edit attempts**. The external capture wrapper applies the same policy to both real production pipelines. All roles, format repairs, malformed/incomplete responses and requests without complete responses are counted. Before requests, conservative admission reserves the UTF-8 bytes of all messages (including system messages) plus the output cap; valid positive provider token usage replaces reservations, otherwise the reservation stays charged. Provider-reported tokens and charged tokens are separate. This is not a model tokenizer or cryptographic billing attestation; chat-template overhead is not independently tokenized. Reported usage exceeding the ceiling is rejected and retained as a budget violation, not hidden. Native operations have timeouts and cancellation waits for their completion; cleanup can overshoot the wall limit and then makes the arm fail its budget predicate. No new request/validation command starts after its deadline.

Original mode behavior remains relevant: the single pipeline has bounded proposal/test retries; multi has task planning, parallel workers, conflicts, diagnosis and model review. Equal ceilings do not mean equal role prompts, call allocation, gates or inference work. This compares complete pipelines, not an isolated model or concurrency treatment. Server caches, thermal/load conditions and fixed model order are not controlled. Reversing mode order reduces one simple order effect; it is not randomization or proof of general superiority.

Both modes receive the same caller-frozen test commands. Model-selected commands are recorded but never executed in this comparison. Generated changes stay in owned worktrees. Both candidates undergo the **same independent external byte-patch replay** onto the original snapshot and the same primary and post-validation commands. A failed candidate remains negative, even if its self-selected command would pass. Requirements remain bound to original command indexes; bindings do not prove completeness of test semantics. Mechanical caller type rules are excluded from the comparison to avoid enabling them only in multi. Other existing coordinator mechanical repairs, if any, are explicitly reported as mode effects.

Frozen plans, normalized answer receipts, patches and completed arm reports are retained. Capture accounting is saved before and after each request; interrupted `started` reservations remain visible. Completed reports and answer digests are verified again before final aggregation. No automatic resume or replacement of an interrupted arm is provided: preserve the incomplete attempt and start a fresh explicit experiment. CLI exit zero means a complete valid comparison report, **not that all coding tasks passed**; `all_tasks_resolved`, per-arm acceptance and budget conformance are separate fields. Every planned arm stays in the denominator. Repetition counts and unique frozen task groups are reported separately.

## Repairs prompted by stage-3 negatives

Single-agent proposals now allow one actual provider format/schema repair, retain the full original objective and scope, and charge malformed/incomplete responses before parsing. Only strict JSON or a single complete JSON fence is parsed; punctuation is not mechanically repaired and scope/source/patch gates remain. Callers can bind frozen test commands and requirements to proposals/runs; legacy callers still retain their original model-selected-command behavior. This comparison uses caller commands in all cases.

Collaboration serializes compact JSON and references code excerpts already present in full authorized source fields. A versioned presentation wrapper has its own digest and exact text hashes/character offsets; restoration reproduces and verifies the original frozen context. Referencing is used only when it reduces serialized size. The context artifact and model receipt still bind the original full evidence digest, while the prompt digest binds the actual presentation. Equal snapshots/scopes still mean equal underlying source views; complete prompts across modes remain different.

Python diagnostic targets must be grounded in actual frames or calls spanning the executed failure line. Earlier passing calls in the displayed module do not authorize changing their functions. Unknown/non-Python or ungrounded failures are refused for this automatic diagnosis path rather than silently broadening scope. This is static syntactic evidence, not proof of causal blame across all dependencies or languages. The native-command fixture rejects an overbroad diagnosis before a repair request.

The internal task has a new explicit `document-history-v2` contract: **every invalid max_messages value raises ValueError**, including bool and int subclasses. It clarifies the original test expectation rather than changing tests to pass generated code. Primary 4 methods, existing document compatibility 10 methods and post 8 methods are the already exercised maintainer cases from earlier stages. They are neither new blind tests nor public benchmark samples. The original stage-3 failures remain failed, and no stage-4 result retrospectively changes them. Post-validation results are never returned to the model in the same arm. Prompt withholding is not OS protection of test files.

## Verification

Initial comparison mechanism suite **10/10, 56.840 seconds**; after deadline/grounded-expression refinement **10/10, 54.431 seconds**. Both precede the final predeclared-repeat/report-integrity refinements. Native tests and model fixtures verify the comparison protocol, not local model coding quality.

An intermediate compatibility invocation had a mistaken unittest class selector: **20 discovered entries, 78.290 seconds, one loader error** (`AutonomousCodingTests` did not exist); the other 19 entries passed. This was a test-command error, not a product pass, and is preserved in `output/coding-comparison-compat-20261007.log`. Corrected compatibility **30/30, 97.549 seconds** and the pre-path-fix comparison suite **12/12, 118.258 seconds** passed.

The first full run discovered **890 tests, 17,332.630 seconds, two errors**: Git status timeout in delivery API verification and an occupied temporary worktree during active-owner test cleanup. It is a failed run, not 890/890. The active-owner fixture now cancels and drains its owned collaboration even when its initial readiness wait fails; no timeout or assertion has been weakened. The fresh final regression below passed.

The first real pilot (`output/coding-pipeline-comparison-20261007`) is unusable for a model comparison: both multi arms failed before any model call when a digest-derived atomic temporary filename exceeded Windows MAX_PATH. Their total was zero calls/tokens and 25.375 seconds. Single arms had four calls, 27,012 charged tokens and no acceptance; the first rejected malformed JSON, and the second had a long interruption with 19,051 charged tokens (only 3,487 provider-reported) and exceeded the wall budget. Their recorded total wall duration of 16,298.798 seconds is not successful active load. The old `protocol_valid=true` only checked source/evidence integrity and cannot turn this pilot into a valid quality comparison. Original reports are retained.

Atomic writes now use a short unique sibling temporary name; comparison arm directories are compact. A zero-call fixture explicitly requires `execution_comparable=false`. This predicate checks actual model admission and wall/token/call compliance, not proof that every failure is model-caused. Evidence completeness, budget compliance and acceptance remain separate. The post-fix suite **14/14, 139.323 seconds** passed; the final 250-character target-path test separately passed **1/1, 1.757 seconds** after tightening its path length. The final source passed isolated full regression **892/892, 1,274.939 seconds**, `output/regression/a07a5fae380d40359422c3b969c6631f`. Existing deprecation, openpyxl and asyncio slow-callback warnings did not block acceptance.

## Actual local results

The fresh post-fix run `output/cc4-20261007-v2` used the unchanged committed task snapshot from `45927e2`, the explicit v2 contract, the same per-arm caps and predeclared order. All four arms actually called the model, stayed within budget and preserved source/evidence integrity: `complete`, `protocol_valid`, `execution_comparable`, `budget_conformant` are true; `all_tasks_resolved` and `model_comparison_available` are false.

| Order / mode | Accepted | Calls | Charged / provider tokens | Recorded seconds | Common replay commands |
| --- | --- | ---: | ---: | ---: | --- |
| 1 / single, repetition 1 | No | 2 | 8,085 / 8,085 | 306.469 | exits 1, 0, 1 |
| 2 / multi, repetition 1 | Yes | 7 | 27,289 / 27,289 | 796.375 | exits 0, 0, 0 |
| 3 / multi, repetition 2 | Yes | 5 | 21,315 / 21,315 | 334.954 | exits 0, 0, 0 |
| 4 / single, repetition 2 | No | 2 | 8,085 / 8,085 | 249.281 | exits 1, 0, 1 |

Both single arms rejected malformed JSON even after one actual format-repair request; neither produced an applicable patch. Both multi arms dynamically split two authorized modules, ran two overlapping client requests, committed their real changes, passed public/compatibility tests, received a separate same-model review and passed all three original/common replay commands, including the eight post methods, in a fresh workspace. There were respectively two and one rejected initial worker responses; the first arm's initial format-repair response also failed before the next worker attempt succeeded. All requests were counted. Neither multi arm used mechanical code repair. No generated business patch was applied to the daily checkout, and this comparison does not produce a separately approved CollaborationDelivery packet or inject process death/conflicts.

Independent post-run audit verifies the frozen plan/order/limits, all 16 normalized answer receipt digests, patch hashes, exact replay commands, accepted worker commits, both checkpoint hashes, eight native context artifacts and twelve native answer/context bindings. All 15 selected runtime/harness witnesses still match. Final report file SHA-256: `cdbeb4b8b2413046935743e9f9f6b99d6a877adbfa1ba8549d361b10a4b500d7`.

Source compilation covers nine changed Python files, bundle `38535a3ae0d53f2975e6705eeab2796c9bf13a22c9c010a5829405fc96129601`.

The explicitly owned model process PID76088 / port18931 was checked against its executable and exact UTC start `2026-10-07T07:11:45.4512840Z`, then exited at `2026-10-07T12:43:26.2227733Z`. An earlier stop attempt refused to act because PowerShell converted JSON dates automatically; string-preserving parsing confirmed a zero-millisecond identity difference before the successful stop. Production and the prior preview were not restarted. Daily database SHA-256 remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`. Final nine-source witness verification and whitespace checks passed. Runtime evidence, model weights, databases and the existing dirty `clawos/skills/skill_registry.jsonl` are excluded from commits.

## Reproduce

Use an explicitly owned local server, fresh output directory and the existing model. This command does not start/restart any server:

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/compare_coding_pipelines.py --live --model qwen9b http://127.0.0.1:18931/v1 Qwen3.5-9B-Q4_K_M --repetitions 2 --out clawos/output/cc4-20261007-v2
```

Evidence includes `provenance.json`, `comparison/plan.json`, progress, per-arm capture/answer/report files, raw binary patches and the final comparison report. Model labels are configured identities, not attestation that remote aliases correspond to distinct underlying weights. Source witnesses cover selected Python runtime/harness files, not every transitive dependency, runtime binary or environment setting.

## Boundaries / next stage

Observed acceptance is multi 2/2 versus single 0/2 on one reused internal task. Role prompts, full source presentation, review and format handling are pipeline differences; this is not an isolated causal estimate of agent count. Temperature zero does not remove context or server-cache effects, and elapsed times are not controlled cold-cache speed comparisons. One local model and one reused project task cannot establish general coding resolution rate or superiority over another product/model. Strict filesystem/socket isolation and `production_sandbox_ready=false` remain unchanged. Larger independent task samples, actual second-model trials and a measured policy for when collaboration helps remain later work. Failure admission into self-evolution is not implemented by this comparison alone.
