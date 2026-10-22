# Self-evolution stage 3 acceptance — 2026-10-04

Continues stage 2 commit `90bdea2` on `codex/coding-agent-competitive-p0-p2`. This phase captures actual configured-provider responses and binds online review/adjudication to assigned server sessions. It does not train weights, rewrite source autonomously, execute tools during answer capture, certify teachers or prove a real-user quality gain.

## Implemented behavior

`EvolutionModelCapture` plans the full paired holdout before execution: at most 200 declared calls, 32–1024 output tokens per answer, 1–60 seconds per call and a 900-second attempt budget. It uses the primary provider with temperature zero and no tools or fallback. Each immutable receipt binds exact messages/options, frozen input/policy digests, provider configuration digest, provider/model, response/text digest, sanitized usage and locally measured duration. Endpoints/authentication/raw responses are not exported. Only nonempty complete `stop` answers without tool calls are accepted. Failures retain partial answers; explicit resume must use the same provider/options and verified receipts. Pausing or a replacement/expired lease fences old workers. Baseline/source/imported-executor drift blocks publication; changes to an active endpoint/model/template configuration also reject the answer. Provider errors cannot leak their text into exported status.

Captured answer text comes from real model execution conditioned on the existing frozen production retrieval/routing replay context. It is not a live agent/tool task execution, a prompt/template experiment adapter, a vector-model test or cryptographic proof of model internals. Application-captured provenance is distinct from external JSON imports, which remain unverified and cannot claim capture receipts.

The owner can assign existing server-issued Collaboration users per experiment as reviewers or adjudicators, revoke the assignment, and provide the review link. Display names and request-body identities confer no rights. Online ratings use the authenticated UID, recheck the session/assignment inside the write transaction, and cannot be overwritten. Roles cannot swap. Credentials remain in HttpOnly session cookies or request authentication and are never stored in review evidence. Unassigned, expired or revoked sessions, cross-experiment access, cross-site writes and invited users trying owner administration are rejected.

`/evolution-review?experiment=<id>` provides readable anonymous A/B answers, bounded scores, reasons, critical-error flags, cross-question in-memory drafts, keyboard navigation and whole-packet submission. Reviewers cannot see other reviews or variant aggregates before submitting. After submission only their own frozen ratings can be reloaded. Switching account clears the previous account's memory drafts. Drafts are deliberately not persisted in browser storage; closing/refreshing an unsubmitted page loses them. The console offers capture budgets/progress/pause/receipts, role assignment, link copying and separate authenticated-vs-imported reports.

A different assigned session user resolves disputed entries or critical-error flags. Each immutable, idempotent decision binds packet/text digests and the exact authenticated review-set digest, with reasons for both scores and error decisions. Adjudicators see pseudonymous original reasons only for their conflicts. Original ratings remain unchanged. A new review changes the snapshot and invalidates old decisions without deleting them. Confirmed critical errors continue blocking acceptance; task support is never inflated by the number of reviewers or adjudicators. Every segment still requires 30 independent matched groups and the existing non-regression gate. No rating or decision becomes live quality signals or automatically activates a policy.

Session authentication proves possession of a server-issued credential, **not** independent people, professional qualifications or independent semantic truth. An owner can create several invited users and can unblind source-accessible answers. `reviewer_identity_verified`, `real_person_independence_verified`, `semantic_entailment_verified` and `runtime_promotion_evidence` remain false. Native authenticated and legacy imported summaries are assessed separately; authenticated results take precedence in the console when present.

## Validation

| Check | Result | Ignored evidence |
|---|---|---|
| Final full isolated Python | **810/810, 502.942s** | output/regression/46456da75df84635a5c4148ee6fde776; output/evolution-stage3-full-final-20261004.log |
| Final stage 3 focused | **20/20, 21.505s** | output/regression/202600f269414de4a3bfbbcb82f82f38 |
| Stage 2 compatibility before final provider drift guard | **21/21, 21.376s** | output/regression/6f13add8514c48c7a26cc9064e56fa2c |
| Final static | **45/45, 0.072s** | output/evolution-stage3-static-20261004.log |
| Node | **17/17, 379.7001ms** | output/evolution-stage3-node-20261004.log |
| Actual local-model HTTP | **12/12** | output/evolution-stage3-http-delivery-20261004/result.json |
| Final actual Chrome | **12/12**, Chrome154.0.8037.95 | output/evolution-stage3-browser-release-20261004/result.json |

The earlier full run passed 809/809 in 480.912s; it was superseded by the final rerun after adding active provider drift protection. Initial fixture failures (unclosed SQLite backup handles, mismatched fixture schema/order, changing adapter class during a resume) were corrected without weakening immutability or gates. Browser-script option waits were changed to stable server UID selection. Actual mobile contrast and inaccessible scroll-region defects were repaired. Actual screenshot inspection also led to own-rating reload and account-switch draft isolation fixes. No failed attempt is reported as a pass.

Final API campaign: 10 synthetic questions, two held-out groups, **4 actual local Qwen responses**, provider alias `stage3-qwen3.5-9b`, 540 reported prompt tokens and 82 completion tokens, 30.421s API workflow elapsed. Server ran the existing Qwen3.5-9B Q4_K_M GGUF through the existing llama-server executable on owned loopback18921, context4096/parallel1/GPU layers20. Tokens are provider-reported, not a monetary estimate. The paired questions ask about frozen allowed tools; this is a protocol check, not independent teaching or strategy effectiveness. Two synthetic session reviewers disagreed, a third synthetic session adjudicated, originals stayed intact, revocation returned403, and the two-group support correctly blocked acceptance. There were additional calls in earlier iterative QA campaigns; final counts describe these final artifacts only.

Final Chrome `154.0.8037.95` uses fresh owned profiles, actual server cookies/forms/downloads and actual primary-provider capture for another four answers. Desktop1440×1000/mobile390×844 checks cover cross-question drafts, incomplete-packet rejection, two frozen reviews, pseudonymous adjudication, own-rating reload, immediate revocation, account switch isolation, keyboard skip link and horizontal overflow. All four automatic axe states returned zero violations. The new review page has no incomplete rules; the existing console retains manual color-contrast/table judgments. Screenshots were visually inspected. Headless desktop/mobile emulation is not real device/independent people/screen-reader speech or multi-day acceptance.

Everyday `memoryos.db` SHA256 before/after remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`. All Python regressions use `scripts/run_regression.py`; QA uses isolated ignored output stores. Production and other previews were not restarted. Only this phase's preview was refreshed. Temporary owned model/preview processes are cleaned up after final checks. Earlier document48h acceptance remains **FAILED**, with heartbeat48 already removed; no new continuous-load or sleep-as-success claim.

## Fingerprints

Final API definition: `e9b2cf9f82c40503e294972fea50614c1519fbf1c2aa3a278317caf6179f542e`.
Final replay report: `544e5da447e4830b920dda044ec72e74336b417c5d450485a3d28b39df4d3104`.
Final packet: `250153aefeab59debaabe8493ee83ed4a8ea741d7202001a325f2bf0f480e73c`.
The hashes below are local working-file bytes; provider/runtime source hashes are also frozen in the API definition. UI/server hashes document the final implementation separately.

| Source | SHA256 |
|---|---|
| services/evolution_experiments.py | a80231f7871831f4c830098347f33a6a246a95980ece83d4d15f3f5511e17bd3 |
| services/evolution_jobs.py | 61b2455768e7365b9f74ada21f8073182f0ffa7b627f549a35d848500c1e8fa8 |
| services/evolution_review.py | 735c374aef0b238cce762797f879f33158e45730d443d77e804cceb39c1348ee |
| services/evolution_capture.py | 44fefb96f728997d20a54c25e08e3ba42eb513a5e00ea38e7c0566c8e146ce10 |
| services/learning_governance.py | e66064258fd0fa3cdd69ee86c3f18bac01b12541ffbdcac2737759c620cb0b82 |
| reflection/evolution_runtime.py | 1fa301ff8eec3aac3438965bdb58a8e1677059cc3e5fd42d8983d2e7d70a1609 |
| memoryos/services/retrieval.py | 102e9410c779300eb56640df31bae27bcaee17fde0cdfbf0b7d99078f92ca6d3 |
| services/knowledge_core_service.py | 6b9cc24d0767d6a4127be19b4b4fe9ba921833b620df513ecca43f6fae5f3f8a |
| memoryos/memory_store.py | b2fcbfaa9995b8ec860d8fed930044c505ee2ba848295c4c131e333604d77e51 |
| providers/base.py | ca81ba13d57dfa9d50348787bce35d803b0aff9778745e829e881b653f21a9f8 |
| providers/openai_compatible.py | 6baffa713afdf9e4071cb37719eac97755801f1768df8986f65e23ed3f7d86a3 |
| providers/qwen.py | 54cca11ba11224b7b732cf73f90f7453d1f37f436c176851900a30c9306ebc45 |
| clawos_server.py | 9c939881100070f24b5bdc28523daf68462e67830346073106f684db2978ac29 |
| static/evolution-review.html | c7201c49ca63747d75c05cd465c8189089a4f02849aba68989e9b7cb678283a9 |
| static/assets/evolution-review.js | 218f01e6f49ca8064ab64277908af8dffaf22760961cbe8baaef4bbdd1b404dc |
| static/assets/evolution-review.css | 8449b0e7c7e9801356d60faf2f1f454d6dea3ab35124a8ef8b0a533757810d60 |
| static/assets/console.js | 55e68f4e4fe021df70cc5d2f8ae7511ccba5f777c38351c034922eb84ce886c6 |
| static/assets/console.css | 9d6c41854557ecbd48de93696107e45e293b3241fc5cabe6ca92ec1d46f520d1 |

## Remaining acceptance and next phase

Subjective engineering closure: **88/100**. This is not an observed learning gain or whole-product score. Remaining work is independently reviewed subject cohorts (at least30 groups in each declared segment), verified teacher/person separation and rubric calibration, semantic near-duplicate and label audits, prompt/report-specific provider adapters, actual vector/document recovery, hybrid-router drift and causal contribution attribution, fresh shadow/canary traffic and controlled multi-day multi-device/reader acceptance. UI user selection currently lists the first100 existing session users; organization directory/SSO and draft persistence need a separate scoped design. Attempt leases require explicit recovery; no autonomous scheduler is claimed.

Reproduce protocol acceptance with the existing local server and `scripts/learning_preview.py --local-provider-url http://127.0.0.1:<owned-port>/v1 --port <owned-preview-port> --session <new-owned-session>`, then `scripts/evolution_stage3_acceptance.py --url ... --out ...`. Browser acceptance uses `scripts/evolution_stage3_ui_acceptance.cjs --url ... --playwright <installed-library> --browser <Chrome> --axe <installed-axe> --out ...`; it does not use personal browser profiles. Repeated engineering fixtures have unique lexical campaign IDs; they do not establish semantic task independence.

Delivery is authorized for Snape-arch/agent and the exact existing branch. Explicitly stage validated sources/tests/scripts/docs only; exclude tools, model weights, credentials, DBs, output and the original `clawos/skills/skill_registry.jsonl` change. No master merge or force push. Final verified remote commit is reported in the completion reply.
