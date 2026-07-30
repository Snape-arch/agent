# Coding Agent Excellence P0-P2

ClawOS now has a software-complete P0-P2 path for improving coding-agent
quality without claiming that real-data, target-hardware, or online-RL gates
have passed.

## Truth boundary

- `software_p0_p2_closed` means the capability, API, audit evidence, safety
  boundary, and deterministic tests exist.
- `production_learning_ready` remains false until observed trajectories,
  explicit feedback, preference pairs, propensity coverage, and OPE support
  pass the existing thresholds.
- `online_rl_claimed` remains false.
- Hardware readiness remains false until a target-device report with at least
  30 real tasks passes.
- No offline model, ranker, adapter, or policy is activated automatically.

## P0: causal evidence and coding context

### Candidate policy causality

`reflection/evolution_runtime.py` passes each baseline and candidate payload to
the isolated frozen/core subprocess. The subprocess records the applied policy
digest and enforces tool-routing candidates. A target-specific runtime probe
also executes prompt, retrieval, routing, or report-template materialization.

Automatic evolution gates require:

- baseline and candidate execution digests;
- both configurations to be materialized;
- a different materialized result when the candidate differs;
- frozen, core E2E, and retrieval non-regression.

### Counterfactual decision evidence

Trajectory steps can store:

- complete candidate set;
- score for every candidate;
- selected action and probability;
- policy version;
- exploration source and random seed;
- context digest.

`services/advanced_policy_learning.py` audits those fields and evaluates a
candidate with IPS, SNIPS, doubly robust estimation, cluster bootstrap,
effective sample size, overlap, temporal holdout, and scenario segments.
Insufficient support aborts the candidate instead of producing an activation.

### Coding Context Kernel

`services/coding_context_service.py` builds a versioned context pack containing:

- managed, project, and path-scoped instructions;
- a strict estimated-token budget;
- task-ranked source evidence;
- Python AST symbols and lightweight cross-language symbols/imports;
- test mappings;
- Git status, branch, head, and recent commits;
- normalized IDE/LSP diagnostics;
- source digest, trust, and precedence metadata.

The existing coding workflow returns this context pack from `inspect`.

## P1: execution and delivery

The coding workflow now supports:

- multi-hunk structured changes with exact-match guards;
- atomic writes and exact pre-change checkpoints;
- automatic repository test-command suggestions;
- allowlisted test execution;
- Python syntax review plus `git diff --check`;
- bounded repair rounds;
- automatic restore on any failed gate.

`services/coding_workspace_service.py` adds explicit-confirmation Git worktree
creation and scoped local commits. It never pushes or mutates a remote.

API:

- `POST /api/workspace/coding/workflow`
- `POST /api/workspace/coding/worktrees`
- `GET /api/workspace/coding/worktrees`
- `POST /api/workspace/coding/commit`

## P2: offline trajectory learning and governance

The advanced learning service contains:

- a temporal-holdout trajectory preference ranker;
- an advantage-weighted-regression dataset sandbox;
- hard trajectory/step thresholds;
- no runtime mutation and no online-RL claim.

API:

- `POST /api/agent-learning/ope/evaluate`
- `POST /api/agent-learning/trajectory-ranker/train`
- `POST /api/agent-learning/offline-policy/sandbox`

Execution governance includes:

- authenticated identity and role checks;
- public-network host/port allow and deny policy;
- hard model-call, tool-call, token, and wall-time budgets;
- deterministic before/after lifecycle hooks with deny support;
- a unified P0-P2 readiness report.

API:

- `GET /api/coding-agent/readiness`

The readiness report separates software closure from real-data and hardware
evidence. This separation is a release invariant.

## Next evidence, not more architecture

1. Collect real coding trajectories with complete counterfactual logs.
2. Run 20-50 repository tasks spanning bug fixes, tests, refactors, and
   cross-file changes.
3. Compare baseline and candidate policies using the same task set.
4. Promote only when OPE support, confidence bounds, safety, and runtime canary
   gates all pass.
5. Add a real LSP process bridge and IDE client after repository-task evidence
   shows that static context is the limiting factor.
6. Consider LoRA only after prompt, retrieval, and router improvements plateau.
