# Coding Agent Product Closure P0-P2

Date: 2026-07-30

## Result

This iteration closes the implementable software and governance gaps from the
latest coding-agent audit. It does not claim real-model quality, online RL,
production learning readiness, or target-hardware acceptance.

## P0: evidence, context, and policy evaluation

- The normal chat and MTClaw paths accept `clawos_coding_context` and inject a
  bounded repository context pack into model messages. Invalid repositories
  fail closed with an explicit unavailable marker.
- Repository symbol/dependency analysis now has a content-addressed incremental
  cache. Cache hit/miss evidence is included in every context manifest.
- Coding readiness no longer fabricates `verified=true`. A durable evidence
  registry validates integrity, expiry, source, type, and latest status.
- `scripts/verify_coding_product_closure.py` records software capability
  evidence only after the focused acceptance suite succeeds; evidence expires
  and must be regenerated.
- OPE accepts per-record target-policy probabilities and uses a
  leave-repository-or-task-group-out reward estimate by default. IPS, SNIPS,
  DR, overlap, ESS, clustered bootstrap, temporal holdout, and segment reports
  remain offline-only.
- The behavioral A/B gate requires at least 30 real, blinded patch cases with
  hidden-test and patch evidence. Synthetic or incomplete cases are rejected.

## P1: model patch loop and coding product contracts

- `AutonomousCodingService` performs a bounded model proposal, strict JSON
  validation, scoped patch, real test execution, review, rollback, and repair
  loop. Writes require `confirmed=true`; no commit is created automatically.
- Every workflow round creates a restorable checkpoint before editing.
- `LanguageServerBridge` performs a real LSP stdio JSON-RPC initialize
  handshake and document-symbol request. Configuration alone never counts as
  availability.
- Worktree delivery now includes a read-only merge plan and refusal to remove
  unregistered or dirty worktrees.
- IDE context, CI evidence, and independent review contracts normalize scope
  and require attributable evidence.

## P2: persistent learning governance

- OPE, trajectory ranker, and offline AWR outputs can be persisted as versioned
  candidates.
- Candidate transitions are constrained to:
  `candidate -> evaluated -> shadow -> active -> rolled_back`, with rejection
  branches. Evaluation/shadow require passed evidence; activation additionally
  requires explicit human approval and at least 30 samples.
- Router, Trajectory RL, Preference Ranker, and behavior-adapter readiness
  remain threshold reports. They do not start training and always report
  `online_rl_claimed=false`.

## Acceptance

- New focused suite: `8/8` passed.
- The suite includes a real fake-server LSP process handshake and a temporary
  Git repository where a model-generated patch is applied, tested, and
  checkpointed.
- Python compilation passed for all changed Python modules.
- Full repository regression: `374 passed, 1 skipped, 0 failed`.

## Remaining external evidence

The following cannot be closed by implementation alone:

1. At least 30 real, blinded repository patch cases comparing baseline and
   candidate model behavior.
2. Real explicit user feedback and calibrated reward trajectories.
3. Target-device throughput, latency, memory, power, and burn-in evidence.
4. Data thresholds for deep Router, Trajectory RL, Preference Ranker, or
   behavior-adapter training.
5. A real editor extension and hosted CI/PR connector. The current release
   provides truthful backend contracts, not those distribution surfaces.
