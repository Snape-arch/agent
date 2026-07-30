# Coding Agent Trust Closure P0-P2

Date: 2026-07-30

## Result

This iteration closes the implementable trust, data-plane, context, and
promotion-governance gaps from the final RL/self-evolution/coding audit. It
does not manufacture external samples and does not claim online RL.

## P0: trustworthy evidence and promotion

- Automated release evidence is accepted only when it comes from a clean
  worktree, names exact test IDs, contains a transcript digest, and matches the
  current Git commit. Expired, tampered, stale-commit, or legacy aggregate
  evidence fails closed.
- Policy reward no longer defaults missing satisfaction to `0.5`.
- Self-evolution canary and activation require 30 independent
  task/session/repository evidence identities. Repeated aggregate snapshots
  contribute zero independent samples.
- UCB policy, lightweight skill router, trajectory critic, and the persistent
  learning-artifact registry share a minimum 30-sample software promotion
  floor. Deeper learning remains governed by the larger real-data thresholds.
- Autonomous coding now writes durable Context, Model, Edit, Test, Review, and
  Failure trajectory steps with content digests and behavior propensity.

## P1: context and coding governance

- Context assembly performs repository-root inference from supplied workspace
  and focus paths and applies a global token budget across system memory,
  retrieval, repository evidence, history, and the current request.
- Conversation compaction now persists a bounded summary before deleting old
  source turns; it is no longer a no-op.
- Normal tool routing and autonomous coding share authenticated identity,
  model/tool/token/time budgets, before/after/failure lifecycle hooks, and
  application-level egress policy.
- CI and reviewer records can be HMAC-signed. When a verification key is
  configured, unsigned or modified provenance is rejected.

## P2: data-gated learning

- Deep Router remains blocked until at least 500 trajectories, 200 preference
  pairs, 100 explicit-feedback records, and 50 exposures per arm.
- Trajectory RL remains blocked until at least 2,000 trajectories, 10,000
  decision steps, 60% feedback coverage, and 99% valid propensities.
- Preference Ranker and behavior adapters retain their scenario-coverage
  gates. No trainer or runtime policy is activated merely because software
  contracts exist.
- `online_rl_claimed=false` remains a hard truth boundary.

## Remaining external work

The following require real use or a separate distribution project:

1. Collecting real, explicit-feedback trajectories.
2. Demonstrating candidate lift on at least 30 blinded repository patch tasks.
3. Reaching the deeper Router, Trajectory RL, Preference Ranker, or LoRA data
   thresholds.
4. Target-hardware validation and multi-day burn-in.
5. Shipping a VS Code extension and hosted CI/PR integration.

