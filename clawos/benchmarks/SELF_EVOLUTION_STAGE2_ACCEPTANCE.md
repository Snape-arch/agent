# Self-evolution stage 2 — recovery, fresh holdouts and review evidence

## Delivered behavior

This phase extends the configuration evolution delivered in b7a27c9. It adds durable experiment recovery, workspace-wide holdout exposure protection, task-segment acceptance and an immutable external-output/blinded-review workflow. It does not claim learned model weights or genuine model quality gains.

### Interrupted experiments

Each attempt has an independent token and a 90-second lease, retained status/reason and timestamps. Each successfully executed case/candidate outcome is saved independently with a digest. Explicit recovery after expiry abandons the old attempt and reuses valid saved outcomes; missing outcomes run through the production function. Pause/cancel immediately fence the old worker, including its failure handler. Completed/failed/cancelled evidence cannot be restarted or overwritten. Final reports record checkpoint reuse and explicitly state that attempts are not continuous-load evidence.

A real Python child process claimed an isolated experiment, ran and saved a routing outcome, then exited through `os._exit(17)`. Regression forced lease expiry to avoid pretending to wait 90 seconds, recovered the experiment, checked exact outcome reuse and rejected the old token's finish. Other checks cover live-lease theft, renewal after expiry, pause/resume, cancellation and checkpoint corruption. This is crash/fencing acceptance, not a sustained crash campaign or multi-day load.

Recoveries are owner-initiated. No scheduler/automatic retry service or preemptive subprocess timeout is implemented. The 180-second replay budget remains checked between cases. A single case exceeding the lease cannot finalize evidence; the owner must recover it. Source/imported-code changes invalidate the frozen experiment instead of resuming under a changed executor. Recorded wall time can include host suspension and must not be reported as continuous successful load.

### Fresh holdout and task categories

The exposure ledger persists across pause, failure, cancellation, target-key changes and renamed groups. Unicode NFKC, case/whitespace normalization and canonicalized routing inputs detect lexical duplicates. Once an input has been used as holdout it cannot enter another experiment; prior search inputs cannot become another experiment's holdout. Search-to-search reuse remains allowed. Freeze checks existing exposures; claims reserve all cases transactionally, preventing two already-frozen overlapping experiments from both running. Historical running/completed/failed records are conservatively backfilled. Exact-definition retries still return the original experiment.

This protects against normalized lexical reuse, not semantic paraphrases, fabricated independent task identities or data copied into a different workspace/database. Conservative reservation can consume a cohort even if a worker fails before its first case. New executor/baseline campaigns require fresh holdout inputs; exposures are not reset to make a run pass.

Frozen cases can predeclare `segment` (default `default`). Every segment must supply at least 30 independent matched task groups per metric and pass the fixed 0.02 non-regression bound, with Bonferroni correction across segments and metrics. Overall average gain cannot hide supported subgroup regression. Variant/segment identity mismatches fail closed. The same segment gate participates in live shadow/canary promotion and stops supported subgroup harm during canary; small initial canary segments alone do not trigger automatic rollback. Live segment names and outcomes remain caller-reported, so independent taxonomy/label verification remains necessary.

### External model outputs and procedural blinded review

Completed search-selected experiments can receive paired external model answers for every frozen holdout case. Imports bind definition/report digests, exact input and policy digests, provider/model identifiers and text digests. They are immutable and idempotent; they do not prove that a provider actually executed those requests. Prompt/template replay still requires a separate provider execution protocol; this phase supports assessing supplied answers for existing retrieval/routing-selected configurations.

Blind exports randomize A/B order per question and omit provider names, variant mapping and policy hashes. A reviewer supplies complete A/B scores in [0,1], rationale, text digest and critical-error flags. At least two distinct named reviewers are required; same-name retries are idempotent, changed judgments are rejected. Reviews add no independent task support: two reviewers of 37 tasks still give 37 independent task groups. Score disagreement >0.25 or any critical-error flag blocks the reported review pass and requests follow-up. Up to five reviewers are supported. This phase detects disagreements but does not implement an adjudication override.

Names are self-reported; an output submitter cannot review under the same supplied name, but real identity independence is unverified. Owners with original source access can unblind, and answer text may itself reveal identity. Results retain `reviewer_identity_verified=false`, `provider_execution_verified=false`, `semantic_entailment_verified=false` and `runtime_promotion_evidence=false`. No scores are inserted into live quality signals and no review upload activates a policy. This is an auditable annotation workflow, not independently certified semantic truth.

Console now exposes checkpoint counts, expired-lease recovery, pause/cancel and review preparation; file import, anonymous packet download, score collection and full evidence download work. Human-readable cards show reviewer/task counts, disagreements, critical errors and per-segment gates; raw JSON is expandable. Existing system-wide readiness details are collapsed by default so they do not dominate this task flow. Responses from older experiment refreshes cannot replace newer state.

## Validation

| Check | Final result | Ignored evidence |
|---|---|---|
| Complete isolated Python | **790/790**, 560.524s | output/regression/484b7870ad384365977a35468db16004; output/evolution-stage2-full-20261004.log |
| Stage2 focused regressions | **21/21**, 28.572s | output/regression/42d5496e83a24da6aa6a25284e7ea232 |
| Existing self-evolution | **8/8**, 43.078s | output/regression/d3397160992f49f8a4847a77b7f73638 |
| Final frontend static | **45/45**, 0.079s | output/regression/cd3ceeff3df047d1a8ed083bfafc2503 |
| Node | **17/17**, 354.9319ms | local Node test output |
| Actual owned HTTP | **15/15** | output/evolution-stage2-http-20261004/result.json |
| Final independent Chrome UI | **12/12** | output/evolution-stage2-browser-final-20261004/result.json |

Complete isolated Python passed **790/790,560.524s**. Final frontend presentation changes were made while full regression ran; affected static and final browser checks passed afterward. The focused run initially failed a literal 37-task fixture assertion: its `group-*` split actually contained 41 groups, unlike the HTTP `fixture-group-*` cohort's 37. Corrected the assertion to use the frozen report's exact count; independent-support minima were not changed. Existing FastAPI/openpyxl/SWIG warnings remain non-blocking; no tests skipped or quality gate relaxed.

HTTP used model-free preview18919/session `evolution-stage2-20261004`, 200 synthetic cases, 163 search/37 holdout groups. Checks cover malformed JSON/object validation, pause/resume, real checkpointed routing replay, segment acceptance, cross-campaign exposure refusal, terminal immutability, version-bound output import, blinded/idempotent packets, two reviews, unverified-provenance boundaries, immutable judgments, cross-site protection and complete evidence retrieval. Synthetic case namespace changes in repeat UI runs separate engineering fixtures; they do not establish semantically independent real-user tasks.

Final Chrome154.0.8037.92 used fresh CI-owned contexts, desktop1440×1000 and mobile390×844. It tested actual file-picker task import, replay, candidate-only nomination, real experiment JSON download, paused-experiment browser recovery, paired-output import, anonymous packet download, two review imports and actual full review JSON download. Desktop/mobile axe returned zero automatic violations, with `color-contrast` and `th-has-data-cells` requiring manual judgment. No real screen-reader speech or physical-device acceptance. Screenshot output/evolution-stage2-browser-final-20261004/viewport.png was visually inspected after replacing the raw default JSON result with readable cards.

Everyday DB SHA256 remains unchanged before/after validation: `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`. Production and previous previews were not restarted. The earlier document 48-hour attempt remains FAILED, heartbeat48 was deleted after its conclusion was pushed; no new long test or continuous-load pass is claimed here.

## Evidence fingerprints

Owned HTTP definition digest: `ec445787df27aceab21e15757db12673a08fed57fc98d00ed62cf286fcfbed03`.
Owned HTTP report digest: `ea9b404da91aa3705f8b7b234e76490bbfc74f40a6eb17ecc9b8d4e24531dbe7`.

| Frozen source | SHA256 |
|---|---|
| services/evolution_experiments.py | 1f34a648708eb7e69a626848564a7e419ae84c5b7f0a885bb0c02da326c36591 |
| services/evolution_jobs.py | 61b2455768e7365b9f74ada21f8073182f0ffa7b627f549a35d848500c1e8fa8 |
| services/evolution_review.py | 167b1c7a1b13035afe940339c6226e7bd51d7c56b5e035d711ef1d26b8dffed1 |
| services/learning_governance.py | e66064258fd0fa3cdd69ee86c3f18bac01b12541ffbdcac2737759c620cb0b82 |
| reflection/evolution_runtime.py | 1fa301ff8eec3aac3438965bdb58a8e1677059cc3e5fd42d8983d2e7d70a1609 |
| memoryos/services/retrieval.py | 102e9410c779300eb56640df31bae27bcaee17fde0cdfbf0b7d99078f92ca6d3 |
| services/knowledge_core_service.py | 6b9cc24d0767d6a4127be19b4b4fe9ba921833b620df513ecca43f6fae5f3f8a |
| memoryos/memory_store.py | 8090a2f72856dd2e23510d062df190b7424e0def04b290e05e913901d7b030dd |

## Reproduction and next phase

Use `clawos/.venv/Scripts/python.exe clawos/scripts/run_regression.py`, focused `--pattern test_evolution_stage2.py`, and `node --test clawos/tests/*.test.cjs`. Use `learning_preview.py --port 18919 --session <fresh-isolated-session>` without models for contract acceptance. `evolution_stage2_acceptance.py` takes `--url` and `--out`; use a fresh preview session for a complete new run. `evolution_stage2_ui_acceptance.cjs` takes `--url`, `--out`, `--cohort`, `--playwright`, `--browser`, `--axe`; a fresh synthetic cohort is generated if none is provided. Evidence stays under ignored output.

Subjective engineering closed-loop score: **85/100** (prior80/100); not an algorithm-novelty or real-task-quality score. Next: independently authenticated reviewers, captured provider request/response evidence for prompt/report and retrieval-answer evaluation, explicit adjudication/versioning, independently grouped semantic datasets, subgroup taxonomy binding, hybrid-policy temporal/drift experiments and contribution attribution. Larger campaigns need scheduled workers, per-case isolation/timeouts and bounded retention. Multi-day reliability remains an independent unmet acceptance requirement.

Delivery follows prior explicit authorization for origin `https://github.com/Snape-arch/agent.git`, branch `codex/coding-agent-competitive-p0-p2`, source/tests/docs only; exclude tools, weights, credentials, databases, output and the original `clawos/skills/skill_registry.jsonl` modification. No master merge or force push. Final remote-verified commit is in the completion response.
