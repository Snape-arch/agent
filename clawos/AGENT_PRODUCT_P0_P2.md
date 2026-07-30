# Agent Product P0-P2 Software Closure

Date: 2026-07-30

## Outcome

This block closes the software contracts identified by the product comparison
with Claude Code and Codex. It does not claim production readiness, signed IDE
distribution, operating-system sandbox enforcement, real-user lift, hardware
validation, or online reinforcement learning.

## P0: One Coding Product Loop

- `clawos.task-run.v2` is the canonical task envelope across API, IDE, web
  streaming, and workers.
- A fail-closed state machine now governs start, approval wait, resume,
  cancellation, failure, completion, and terminal-state protection.
- Task events carry transitions, checkpoints, approvals, diffs, tests, tools,
  policies, and completion evidence.
- Checkpoints are attached to the task event graph with URI and digest.
- The VS Code source integration creates the canonical TaskRun, synchronizes
  state, opens Git changes in the native editor view, retains the last
  checkpoint, and exposes an explicit rewind command.
- Failure and cancellation attempts update the canonical run instead of leaving
  an invisible running task.

## P1: Programmable and Governed Platform

- `PolicyHookRegistry` now exposes a v2 lifecycle with session, instruction,
  permission, tool, subagent, task, checkpoint, worktree, compaction, file, and
  configuration events.
- Hook registration supports matcher, priority, scope, and handler type metadata
  while preserving the existing synchronous policy enforcement path.
- Plugin manifests are default-deny and validated for known, explicitly granted
  capabilities, safe entrypoints, semantic versions, and stable digests.
- `AgentSDKRegistry` provides a small typed registration surface for agents,
  tools, context providers, evaluators, and hooks.
- Multi-agent graphs validate typed roles, dependency integrity, cycles, explicit
  budgets and permissions, and worktree isolation for writing agents.
- Sandbox plans validate workspace roots, default-deny network policy, brokered
  secret references, and resource limits. The report fixes
  `os_enforced=false` until a real backend probe artifact exists.

## P2: Transparent Personalization and Governance

- Context explanations expose selection reasons, source priority, trust,
  instruction precedence, truncation, token budget, diagnostics, and digests.
- Memory explanations expose source, confidence, evidence, versions, enabled
  state, and user controls.
- Memory enable/disable changes require explicit confirmation and create a
  versioned governance change.
- TaskRun event replay and the checkpoint graph provide one audit surface for
  execution, policy, tests, and recovery.
- Product Readiness now checks these contracts while preserving
  `product_ready=false` when empirical, signed distribution, OS isolation, or
  advanced-learning evidence is missing.

## API

- `GET /api/agent-product/contracts`
- `POST /api/agent-product/task-runs`
- `GET /api/agent-product/task-runs/{task_id}`
- `GET /api/agent-product/task-runs/{task_id}/events`
- `POST /api/agent-product/task-runs/{task_id}/transition`
- `POST /api/agent-product/context/explain`
- `GET /api/agent-product/memories/{memory_id}/explain`
- `POST /api/agent-product/memories/{memory_id}/enabled`
- `POST /api/agent-product/plugins/validate`
- `POST /api/agent-product/agent-graphs/validate`
- `POST /api/agent-product/sandbox/plan`

## Verification

- Focused agent product/runtime/coding/readiness suite: 32 tests passed.
- Full repository regression: 396 tests passed, 0 failed.
- Python compilation passed for all changed Python modules.
- Bundled Node syntax validation passed for the VS Code extension.
- Only pre-existing FastAPI `on_event` and PyMuPDF/SWIG deprecation warnings
  remain.

## Truth Boundary and Next Step

This is a software-contract closure. The next engineering priority is to
replace the sandbox plan with a probed Windows/Linux backend, package and sign
the VS Code extension, and exercise the unified TaskRun protocol through real
long-running repositories. Data-gated Router, Trajectory RL, Preference Ranker,
and behavior LoRA promotion remain blocked and `online_rl_claimed=false`.
