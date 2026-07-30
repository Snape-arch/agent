# Coding Agent Competitive P0-P2 Closure

Date: 2026-07-30

## Outcome

This iteration closes the next software-only P0-P2 slice for coding-agent
context, execution, offline learning, and release governance. The readiness
gate remains fail-closed and `online_rl_claimed=false`.

## P0: trustworthy production path

- `/api/workspace/coding/autonomous` now runs the bounded
  `AgenticCodingLoopService`, requires `task_id` and `session_id`, and writes a
  durable Context/Model/Tool/Edit/Test/Review trajectory.
- Trace updates are atomic within a process and include content digests,
  task/session identity, action-policy metadata, and terminal integrity
  digests.
- Invalid model actions and invalid observation requests become recoverable
  trajectory evidence instead of leaving a run silently incomplete.
- The trusted review API fails closed unless
  `CLAWOS_REVIEW_SIGNING_KEY` is configured. A local signing utility produces
  HMAC evidence without passing secrets through the API.
- Long conversations are compacted automatically; the semantic summary is
  persisted before old messages are deleted.

## P1: coding loop, context, and entrypoints

- The agent now selects one action per turn: search, read, inspect symbols,
  propose a patch, or finish. A finish action is accepted only after real patch
  and test evidence.
- Repository instructions support `AGENTS.md`, `CLAUDE.md`, `.clawos/rules`,
  and `.claude/rules`. Frontmatter path/glob rules are included only when they
  match ranked task files.
- The LSP bridge keeps one initialized process per repository/command and
  supports symbols, definitions, references, hover, rename, and diagnostics.
  Open-document versions are synchronized across persistent requests.
- A headless CLI supports text, JSON, streaming JSON, and a bounded JSON-schema
  output check.
- A VS Code extension source MVP captures open files, selection, and
  diagnostics, normalizes them through a repository-scoped API, and opens a
  confirmation-gated coding proposal. It is not yet packaged or published.

## P2: leakage control and self-evolution governance

- Agent Skill Policy Network data is split by repository/task/session group.
  Training and holdout IDs are persisted and disjoint.
- Trajectory Critic evaluates only the persisted holdout and derives its
  outcome estimate from training-arm means, rather than reusing candidate
  policy scores as a reward model.
- Self-evolution promotion requires at least 30 independent, paired
  control/candidate identities. Candidate regressions against control block
  promotion, and control observations no longer pollute the candidate health
  aggregate.
- The release-evidence verifier maps every readiness capability to exact test
  IDs, refuses dirty worktrees, binds evidence to a Git commit, and expires it.

## Verification

- Competitive/RL/self-evolution focused regression: 35/35 passed.
- Root test discovery: 381 passed, 1 skipped, 0 failed.
- Python compilation, VS Code extension JavaScript syntax, and
  `git diff --check` passed.

The skipped test and deprecation warnings are pre-existing and non-blocking.
Commit-bound release evidence must be generated only after this change is
committed from a clean worktree.

## Truth boundary and remaining priority

Software mechanisms are closed; empirical product claims are not.

1. **P0 — real data and reward calibration.** Collect at least 50 task-bound
   trajectories and explicit feedback, preserve behavior propensities, cover
   every active arm, and calibrate reward on a task-disjoint holdout.
2. **P0 — operating-system sandbox.** Validate process/filesystem/network
   containment on the target hardware. Application-level path and egress
   policy is not an OS sandbox.
3. **P1 — real coding benchmark.** Run 30-50 blinded repository issues against
   a fixed baseline and report patch success, regression rate, latency, cost,
   and rollback rate.
4. **P1 — productize IDE/headless delivery.** Package and sign the VS Code
   extension, add cancellation and live progress, and validate the CLI in CI.
5. **P2 — learning expansion only after gates pass.** Build a Preference
   Ranker after 100 valid pairs. Re-evaluate a deeper Skill Router or
   Trajectory RL after 500-2000 diverse, propensity-complete trajectories.
   Behavior LoRA remains later than those gates.

Until those empirical gates pass, the project must not claim online RL,
production model lift, target-hardware validation, or production-ready IDE
distribution.
