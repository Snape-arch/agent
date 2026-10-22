# Paired self-evolution experiments — 2026-10-03

## Delivered behavior

First implementation phase: common evidence gates, bounded reflection-driven configuration search, frozen read-only replay and a usable strategy experiment console. This is native configuration optimization; no claim of GEPA training, online RL, automatic source changes or weight training.

- Reflection failure categories and repeated patterns rank at most three distinct changed candidates. Retrieval parameters, prompt instructions, report sections and restricted routing configurations retain their existing allowed scope. Hypotheses explicitly carry `verified_gain=false`; routing cannot expand tool permissions.
- Frozen experiments retain reviewed labels, exact input digests, baseline policy version, source hashes and imported executor fingerprint. Exact duplicate inputs are rejected; task groups remain together in deterministic search/holdout partitions. Claims are atomic across independent database connections; definitions and finished reports are immutable. Nomination is idempotent and rejects stale policy/source/executor state.
- Built-in retrieval replay runs production ingestion and retrieval against a temporary frozen corpus, with environment reranking and vectors disabled. Routing replay materializes the production routing contract without executing tools. Search selects a quality/context-size Pareto candidate without holdout labels; only that candidate is paired with baseline on independent holdout groups. Ties prefer baseline. Nomination creates a candidate, never activates a policy or fabricates live observations.
- Common live quality gates require the same metric on matched task inputs, reject conflicting duplicate evidence, isolate server-observed release stages, and exclude aggregate snapshots/offline probes. At least 30 independent task clusters per metric, deterministic cluster bootstrap, multiple-metric correction and a fixed 0.02 non-regression tolerance are required. Activation needs fresh canary evidence; shadow evidence cannot be reused as canary support.
- Legacy UCB promotion now nominates a governed candidate; direct legacy arm publication and unbound rollback are blocked. Advanced routing logs actual eligible arms, scores, propensity and policy version. Network activation uses complete held-out traces with row/task-cluster ESS, overlap, estimator agreement, paired lift bounds and safety checks; repository groups stay disjoint. Legacy missing traces are rejected rather than invented.
- Console supports candidate comparison, labelled JSON upload, freezing, replay, nomination and actual evidence download. It exposes insufficient/stale evidence and keeps release actions closed. Mobile overflow and keyboard access to scroll regions were repaired. An existing legacy readiness panel remains above this workflow; reduced previews do not serve every legacy readiness API.

Full regression also exposed an empty-lock initialization race in Windows file transactions. Removed the unlocked initialization write; bounded contention regression now passes. Windows supports locking beyond EOF, as documented by [Microsoft LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex); see also [CPython msvcrt documentation](https://github.com/python/cpython/blob/main/Doc/library/msvcrt.rst).

## Verified results

| Check | Final result | Ignored local evidence |
|---|---|---|
| Complete isolated Python | **769/769**, 445.560s | output/regression/0e809cd2dd8145e59f1bcd3eab8c2d42; output/evolution-full-verified.log |
| New experiment regressions | **28/28**, 13.112s | output/regression/a701555734664bc8993862a29ddc0fe4 |
| File/history contention | **20/20**, 4.744s | output/regression/dac6ebab20214d11be1f1ce3734494b4 |
| Final frontend static | **45/45**, 0.072s | output/regression/9e93d8c0ec004498b5d61fd662444ef1 |
| Node | **17/17**, 313.8138ms | local test output |
| Actual isolated HTTP | **10/10** | output/evolution-experiments-http-final-20261003/result.json |
| Independent Chrome UI | **9/9**, Chrome154.0.8037.92 | output/evolution-experiments-browser-20261003/result.json |

Full Python passed before final frontend-only layout/focus changes; affected static and browser checks passed afterward. Intermediate failures included an accidental indentation error, a stale literal label assertion and the real Windows empty-lock race; all were repaired before final results. Imported-code fingerprinting originally used unstable marshal interning state; immutable bytecode/constants replaced it and stability is regression-tested. No gate was weakened to make fixtures pass.

HTTP used an owned model-free loopback preview18918, session `evolution-experiments-final-20261003`: 200 synthetic routing cases, **163 search / 37 holdout groups**. Checks cover bounded candidates, cross-site write rejection, duplicate input rejection, idempotent freeze/nomination, real routing replay, immutable reports and no live-stage bypass. Engineering fixtures establish executable behavior, not user-task quality improvement.

Chrome used fresh CI-owned contexts, desktop1440×1000 and mobile390×844. File-picker import, completed replay, candidate nomination with zero live evidence, actual downloaded JSON, mobile containment and no uncaught page errors passed. Desktop/mobile axe returned **zero automatic violations**; `color-contrast` and `th-has-data-cells` incomplete items still need human judgment. No real screen-reader speech or physical multi-device result is claimed. Initial in-app-browser download-event capture was unavailable; independent Chrome verified an actual JSON file. Final viewport screenshot: output/evolution-experiments-browser-20261003/viewport-final.png.

Everyday database SHA-256 before/after isolated validation remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`. Production was not restarted; tools, weights, credentials, databases, output and the original skill registry modification are excluded from delivery.

## Immutable HTTP evidence fingerprint

- Definition digest: `509cde22fae9ce6bcd05d59c67916012a8ee9024dd0144c7ed5ad2bce1432fd8`.
- Report digest: `ed861c4af713ba9a2954f2bccfd4101ce3acfce0b9661a6a1305d2baab9fa84e`.

| Frozen source | SHA-256 |
|---|---|
| services/evolution_experiments.py | f89ac1c88a0fc7c3de6c4ac09c2e1aaae9ddbaefaefb8ae54ac31c6ed5c3470d |
| services/learning_governance.py | 98d9212d0d9325655e2eb6eb871bff33da3399d5746c84485318850f1b1c14b1 |
| reflection/evolution_runtime.py | 1fa301ff8eec3aac3438965bdb58a8e1677059cc3e5fd42d8983d2e7d70a1609 |
| memoryos/services/retrieval.py | 102e9410c779300eb56640df31bae27bcaee17fde0cdfbf0b7d99078f92ca6d3 |
| services/knowledge_core_service.py | 6b9cc24d0767d6a4127be19b4b4fe9ba921833b620df513ecca43f6fae5f3f8a |
| memoryos/memory_store.py | f313034f9cd066188479ab47b02199253f0449547c94c9549d3c90ede630adbb |

Imported-executor digests are included in each downloaded definition/report. They complement file hashes for long-lived workers; they are not a complete fingerprint of interpreter, libraries, globals or hardware.

## Remaining limits and next experiments

Subjective **self-evolution engineering score: 80/100**, for this local product's closed-loop implementation. This is not an independently measured quality gain or an algorithm novelty score.

1. Reviewer identity is self-reported. Exact duplicate rejection does not detect semantic paraphrases or forged group identities; independently reviewed real task sets and disjoint repeated-campaign holdouts are required.
2. Retrieval measures labelled source inclusion and citation coverage, not answer entailment. Real providers, teacher-blinded semantic labels, vectors/reranker recovery and prompt/report generation replay remain unverified. Context characters are a resource proxy, not measured token price.
3. Network offline evaluation models pure-network argmax on logged eligible arms; live hybrid UCB behavior is different. Temporal/segment reports are diagnostic; live drift, subgroup acceptance and contribution attribution still need dedicated experiments.
4. A worker crash can leave an experiment claimed as running; no lease recovery, cancellation or resumable replay is implemented. Replay is bounded to 180s checked between cases, not a preemptive subprocess timeout. Large campaigns need durable workers and bounded per-case execution.
5. Live outcomes are task-bound self-reports rather than independently authenticated semantic judgments. More data alone cannot fix unreliable labels. Collect independent matched shadow and canary task evidence before any release claim.
6. Multi-day reliability remains unmet: the separate document collaboration attempt failed at 17526.89s, including a 5453.69s coverage gap and 14 errors. See DOCUMENT_STUDIO_ACCEPTANCE.md for preserved true counts/fingerprints. It was one-host API/SSE load, not multi-device browser or screen-reader acceptance.

## Reproduction and delivery

Use `clawos/.venv/Scripts/python.exe clawos/scripts/run_regression.py` for isolated full regression, or `--pattern test_evolution_experiments.py` for focused checks. Use `node --test clawos/tests/*.test.cjs` for Node. Use an owned model-free `learning_preview.py` session; HTTP script takes `--url http://127.0.0.1:18918 --out clawos/output/<new-run>`. Browser script takes `--url`, `--out`, `--playwright`, `--browser` and `--axe`; both assert the isolation marker before writes. Output paths stay ignored. Repeating synthetic fixtures cannot establish real-task improvement.

Authorized delivery: origin `https://github.com/Snape-arch/agent.git`, branch `codex/coding-agent-competitive-p0-p2`; no force push or master merge. Final delivery identity belongs in the completion response after remote verification.
