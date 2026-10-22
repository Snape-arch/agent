# Coding Agent Evaluator Data P0-P2

Date: 2026-07-30

## Outcome

The evaluator data loop is closed in software and has been exercised with a
real local model. Empirical training gates remain closed.

Codex may submit feedback as a single evaluator when it actually runs the
task, inspects the patch, and verifies hidden tests. Such feedback is labelled
`codex_evaluator`; it counts as grounded task-quality evidence but never as an
independent human user.

## P0: provenance and reward data

- Feedback records distinguish `human_user`, `codex_evaluator`, and
  `automated_test`.
- Codex evaluator feedback requires an evidence digest and evaluation method.
- Data-quality reports expose grounded feedback, origin counts, independent
  human owners, and evaluator owners separately.
- Unknown model-action probabilities are stored as zero and excluded from
  propensity-complete OPE data.
- Reward calibration may use test-grounded evaluator feedback, but still
  requires 50 completed trajectories and 20 grounded feedback records.
- Personal preference learning still requires real preference pairs and does
  not infer multiple users from one Codex evaluator.

## P1: real local-model collection

`scripts/run_local_coding_evaluator.py` creates a controlled Git repository,
runs the real Agentic Coding Loop against an OpenAI-compatible local model,
executes repository and hidden tests, persists the task trajectory, and records
evidence-bound Codex feedback.

Observed local run:

- Model: Ollama `qwen3.5:0.8b`, Q8
- Real model executions: 3
- Controlled fixture tasks: 3
- Passed: 0
- Mean duration: about 12.0 seconds
- Persisted task trajectories: 3
- Persisted decision steps: 10
- Grounded Codex feedback records: 3
- Independent human users: 0
- OPE-eligible decisions: 0

The first run repeatedly violated the strict action schema. The second exposed
an uncaught invalid-patch-plan error, which is now a recoverable observation.
The third completed search/read/patch/test cycles but produced patches that
removed the expected function, so tests failed and the workflow restored the
repository.

These are valid negative samples. They show that the collection and recovery
loop works and that this 0.8B model is not currently a reliable coding model.

## P2: learning readiness

Current local observed-data gates remain:

- Reward calibration: blocked
- Preference Ranker: blocked
- Deep Router: blocked
- Trajectory RL: blocked
- Behavior LoRA: blocked
- Online RL claimed: false

Controlled fixtures do not count toward the minimum 30 real-repository
behavioral benchmark cases. Unknown action propensities do not count toward
the 99% propensity-completeness gate.

## Reproduction

```powershell
python clawos/scripts/run_local_coding_evaluator.py
python clawos/scripts/run_local_coding_evaluator.py --summary-only
```

Local reports are written under ignored `output/coding-evaluator/`. The local
database is also ignored and is not committed.

## Next priority

1. Repeat the evaluator with a coding-capable local model.
2. Collect at least 30 real-repository blinded cases, not generated fixtures.
3. Reach 50 completed trajectories and 20 grounded feedback records before
   fitting Reward Calibration.
4. Collect actual user preference pairs before personalization.
5. Keep Router RL, Trajectory RL, and LoRA disabled until their existing gates
   pass.
