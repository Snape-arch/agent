# ClawOS Engineering Roadmap

## Current Baseline

The project already has a usable competition prototype:

- DeepSeek and OpenAI-compatible model provider abstraction
- MTClaw-style function routing and local tool execution
- Five unified long-term memory types
- Rule-based and model-assisted reflection
- Solidified local skills
- A browser workspace with memory, reflection, skills, and tool traces

The current architecture is suitable for a single-user prototype. It is not yet an
enterprise multi-user system, and claims such as 95% accuracy or sub-second learned
task execution need a reproducible benchmark before they are presented as measured
results.

## Phase 1: Reliable Demo Core

Target: a stable DeepSeek-backed end-to-end demo.

- Keep one configurable model-provider contract for DeepSeek and later local Qwen.
- Add streaming responses and cancellation.
- Add structured request IDs, trace IDs, and JSON logs.
- Make every memory write immediately searchable.
- Add memory provenance, conflict detection, version history, and manual review.
- Persist complete reflection cards instead of reconstructing them from experiences.
- Add a benchmark set for the four competition scenarios.
- Package startup, configuration validation, and health diagnostics.

Exit criteria:

- Fresh install starts with one command.
- The four demo scenarios run without manual database edits.
- Every task has a trace, tool result, reflection decision, and memory evidence.
- Automated tests cover provider failure, confirmation, memory retrieval, and restart.

## Phase 2: Local Model Migration

Target: switch from DeepSeek API to an offline OpenAI-compatible endpoint without
changing agent business logic.

- Deploy Qwen through vLLM-MUSA on the target MTT AIBOOK.
- Add a local model readiness probe and warm-up workflow.
- Separate routing and answer-generation model profiles.
- Measure first-token latency, tokens per second, memory footprint, and tool accuracy.
- Add prompt and tool-schema compatibility tests for the selected Qwen checkpoint.
- Provide DeepSeek fallback only in development profiles.

Exit criteria:

- Offline mode passes the same scenario benchmark as DeepSeek mode.
- No network request is required in the competition deployment profile.
- Model switching is configuration-only.

## Phase 3: Industrial Agent Runtime

Target: auditable, recoverable, policy-controlled execution.

- Split API, orchestration, memory, and worker responsibilities.
- Introduce durable task state, retries, idempotency keys, and resumable workflows.
- Add role-based access control, encrypted secrets, audit events, and data retention.
- Sandbox code and shell tools with explicit path and command policies.
- Add observability for latency, token cost, tool success, memory hit rate, and failures.
- Add backup, migration, and database integrity procedures.

Exit criteria:

- Interrupted tasks can resume safely.
- High-risk operations require policy approval and produce an audit record.
- Service-level objectives and dashboards exist for core workflows.

## Phase 4: Self-Evolution With Guardrails

Target: measurable improvement rather than uncontrolled prompt mutation.

- Store strategy candidates and versions.
- Evaluate changes against frozen regression tasks before promotion.
- Implement contextual bandit selection for tools, prompts, and agents.
- Use explicit reward components: success, user feedback, latency, and resource cost.
- Require rollback support and human approval for production strategy changes.

Exit criteria:

- A promoted strategy demonstrates statistically meaningful benchmark improvement.
- Every change has evidence, version history, and rollback.

## Frontend Direction

The workspace should evolve into a task control plane, not only a chat page:

- Live token streaming, stop/regenerate, and editable messages
- Task graph and step-level progress
- Expandable tool inputs, outputs, duration, and confirmation history
- Memory review inbox with provenance, confidence, conflicts, and merge actions
- Reflection comparison showing before/after strategy and measured effect
- Skill editor with visual steps, parameters, dry-run, versioning, and rollback
- Command palette, keyboard navigation, responsive layout, and accessibility checks
- Real-time updates through WebSocket or server-sent events

## Immediate Next Sprint

1. Implement model streaming and cancellation.
2. Persist full reflection cards and user feedback.
3. Add memory conflict/version APIs and review UI.
4. Repair generated skill replay scripts and add dry-run validation.
5. Build four deterministic end-to-end demo tests.
6. Add structured logging and an operations diagnostics page.
