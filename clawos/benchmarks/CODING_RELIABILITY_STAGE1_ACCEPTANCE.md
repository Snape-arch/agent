# Coding reliability: caller contracts and failure diagnosis — 2026-10-07

This starts the ordered coding-capability plan with requirements/verification binding and diagnosis-driven repair. The final isolated regression and both real-model project runs below passed. Earlier small synthetic successes do not replace the project-task counterexamples.

## Implementation and boundaries

- `CodingContracts` validates optional caller-owned `requirements`: unique ID, bounded statement, authorized paths and indexes into the caller's frozen test-command list. All writable paths need coverage. Frozen copies prevent caller aliasing; recovery rejects changed request bindings. The planner must assign every required path. Workers receive relevant requirements alongside the frozen original objective, without extra write permission.
- Runtime records expose requirement ownership, per-command verification results and requirement digest. Results mean the bound commands actually returned zero; they do not prove the caller's tests fully express every statement. One command can cover several requirements. Model review cannot override a failed command.
- Fresh delivery freezes the requirements, digest and re-executed verification results in the immutable manifest. Inspection/acknowledgment rechecks task ownership and bindings. Old runs with no requirements retain their protocol and can be explicitly recovered. A ready packet is not human approval or source application.
- Actual failing Python tracebacks provide bounded read-only snippets from tracked repository files, including the enclosing test function and its called symbols. Outside-repository, sensitive-path, symlink, non-Python and oversized files are excluded. This is contextual evidence, not independent code-execution isolation or an adversarially authenticated traceback.
- With declared requirements, general repair first captures a separate model diagnosis with a hypothesis, existing authorized target symbols and expected test effect. The repair request sees the actual failed assertions and only the diagnosed source paths; patch scope cannot expand beyond them. A rejected no-op remains a failed attempt and receives feedback within the existing shared budget. This does not yet implement stronger-model escalation, a general theorem prover or automatic minimized repro generation.
- An optional **caller-declared** `python_exact_type` rule permits mechanical normalization of direct `isinstance(parameter, Builtin)` calls inside the named top-level function after a failed bound test references that function. Rebinding, nested scopes and shadowed builtin names are refused. Byte-based AST spans preserve Unicode and source layout. No arbitrary imports, coercions, exception branches or unspecified semantics are invented. Actual tests run again after the scoped commit. The event says `model_generated=false`; this contribution must not be attributed to the model's semantic repair ability.
- HTTP `/api/subagents/run`, `autonomous_subagents` and its tool schema accept requirements. No new graphical requirements editor, external identity attestation, distributed scheduler or automatic production application is claimed.

Example declaration (indexes refer to the caller's `test_commands`):

```json
{
  "id": "history_exact_bound",
  "statement": "When supplied, max_messages must have exact builtin int type and be positive; reject bool and subclasses.",
  "paths": ["clawos/services/response_contract.py"],
  "test_indexes": [0],
  "rule": {
    "kind": "python_exact_type",
    "function": "request_history",
    "parameter": "max_messages",
    "builtin_type": "int"
  }
}
```

## Preserved project-task failures

The isolated source slice contains **326 committed Python files, 4,524,940 bytes**, from `e5b37053a89b41274a9e8b29fc376dcffb636f1d`. Only document merge and response history are writable. These are successive development revisions of an internal task, **not four independently sampled benchmark tasks or a corpus success rate**.

| Prior evidence under ignored `output/` | Actual result | Wall seconds | Calls / charged tokens |
| --- | --- | ---: | ---: |
| `collaboration-project-live-20261006/report.json` | FAIL: reviewer input exceeded the two-slot server's actual 4096-token per-slot context; original 14 caller tests passed | 204.281 | 5 / 41,986 |
| `collaboration-project-live-v2-20261006/report.json` | FAIL: public/replay tests and model review passed, but post-delivery exact-type subclass assertion failed; one actual worker timeout was retried | 388.219 | 5 / 15,930 |
| `collaboration-project-live-v3-20261006/report.json` | FAIL: original-objective propagation alone did not resolve the same contract error; format repair succeeded, model review again approved, post-check failed | 486.344 | 5 / 14,177 |
| `collaboration-project-live-v4-20261006/report.json` | FAIL: explicit contract plus promoted public regression still failed; two repair proposals were rejected as no-ops, no handoff prepared | 472.109 | 7 / 20,319 |

The original four post-check methods became diagnostic regressions after observation. Two further methods were exercised in v3, and two more were frozen before v4. The current eight-method post-check is a combination of six exercised regressions and two additional cases not provided to workers. It is maintainer-authored, not independently blinded external evaluation. No post-check failure output is sent to workers in the same run. Compatibility execution does not prevent malicious generated code from reading other local files; prompt withholding is not strict sandbox confidentiality.

`coding_oss_corpus_v1.json` still has no scoreable public-project cases. Its inverse-repair mechanism applies a supplied repair, so a successful inverse repair must never be represented as model-generated task resolution.

## Current verification

The focused contract suite passed **7/7, 34.936 s**; harness discrimination/snapshot tests passed **4/4, 6.073 s**. These use mock model replies/native fixture commands and verify the mechanisms, not model task success. Final isolated full Python regression passed **866/866, 1,524.613 s**, exit zero, `output/regression/799beed7383c4c83a1a4b4331b9d934f`; log `output/coding-contracts-full-20261007.log`. All current source/schema changes preceded discovery; subsequent changes are documentation only. Existing SWIG/openpyxl/asyncio slow-callback warnings remain non-blocking. Final Python compilation, JSONL parsing and whitespace checks passed; JSON Schema was not formally validated with a schema engine.

Both live runs use the same six loaded source fingerprints, existing local Qwen3.5-9B Q4_K_M, temperature zero and two parallel slots (16,384 total context / 8,192 per slot). Limits: 1,800 wall seconds, 300 seconds per request/test, 50,000 charged tokens. Cache/load differences make their wall times unsuitable for a speed comparison. Separate review is another request to the same model, not independent expert review.

| Final evidence under ignored `output/` | Actual result | Wall seconds | Calls / charged tokens |
| --- | --- | ---: | ---: |
| `coding-contracts-project-live-20261007/report.json` | PASS: dynamic two-node plan, peak two worker requests, original 4 public + 10 compatibility methods, fresh replay of both commands, 8 post-check methods, all four requirement bindings | 486.953 | 5 / 14,681 |
| `coding-contracts-project-recovery-20261007/report.json` | PASS: same gates, actual owned child exit 17 twice, exact completed commits reused, interrupted history worker replaced, peak two requests | 429.016 | 6 / 22,286 |

Each run retained one actual malformed worker JSON reply and a successful separate format-repair request. Neither run used coordinator contract/import repair or the diagnostic repair path; exact-type validation came from the candidate patch. Therefore live evidence validates the new requirement-aware task/delivery/recovery path, while diagnostic and mechanical repair are currently supported by fixture tests. The recovery ledger includes a reserved charge for the interrupted in-flight request whose receipt was never persisted; six starts and five retained receipts are not six complete answers.

The first crash froze merge commit `d156ffae91ef590bf24047f75bac9c11b0066240`; the second froze that same merge commit and history commit `dbd8319501bba9cbc76032e3396b2896edb244b4`. Parent recovery retained both verbatim. This proves explicit same-host recovery at two durable-worker boundaries, not arbitrary corruption recovery, distributed failover or sustained load. Normal first run has zero injected deaths; its vacuous recovery check is not fault acceptance.

Requirement digest: `3efecd0d8ac4b40c9a1dd0924a1a7e89daed78693323e589e1504128cff15b3e`. Final report SHA-256: live `b96f0ad2c65e36a14adf0659e277ad379bce18a199cf7c1eb38b04744cd9a3a4`; recovery `001047dd385a16de09ec65497b9b4a0fc17028cb7ba8652efd132c3025a0f2b5`.

Ten-file final code/schema/test bundle (canonical sorted path/hash JSON): `70905a82404123d247d10c220b5dd0f7cdf88a63c2990bd9eb6f4168e0751557`. Manifest: ignored `output/coding-contracts-source-fingerprints.json`. Live witnesses: collaboration `516a54b09419325904092e124c4dad66a41ead2a6cbb5f1bb73afec58e4f8520`; delivery `95bcbf81e9ee6d73ec15454b3b2782db51deecb70c9bb8882a7632c3bd554c24`; contracts `1c76ba9d3256a452031287ef445080c23c2c8d28224772917a506d647311fb7d`; harness `990f8e8ef624ea970736e4a0179b54247b128b5facbae403fca3e3c85f141f80`; unchanged workflow `b82e650f2a22cbeea938f5e5fec7ec37474a5cfa3672ea1f257e72aedaedd452`; unchanged OS executor `8b8c2eda008a27bc98eea9a8d059178b6636caa13de0fdbfb25c95b98dd37860`.

Owned loopback helper port 18929 / PID 59456 was stopped after matching the exact executable and UTC start `2026-10-06T16:04:54.2168541Z`; its stop record is ignored under `output/coding-contracts-model-20261007/stopped.json`.

Daily database SHA-256 remains `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`. The already-dirty skill registry changed checksum during verification; its current content is preserved and excluded from staging, without attributing concurrent changes or restoring another contributor's draft.

No source application of the generated two-module task is included. Existing executable/model weights are only read by an owned loopback helper; production and unrelated previews remain unchanged. Strict filesystem/non-bypass network isolation and multi-day/physical multi-device acceptance remain unproven; the earlier document 48-hour failure stays failed.

Next ordered work after this gate: unify coding context across execution modes; compare models and single/multi-agent strategies with equal frozen tasks/budgets; expand real task sampling; admit failures into self-evolution only with fresh held-out evaluation. None is marked completed here.
