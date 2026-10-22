# Learning and Agent Product P0-P2 Software Closure

Date: 2026-07-31

## Outcome

This block closes the highest-priority software gaps found in the comparison
with Claude Code and Codex. It unifies Academy mastery with durable backend
evidence, adds an explainable learner model, binds coding project evidence to
canonical TaskRuns, and gives context and coding review one TaskRun evidence
ledger.

It does not claim real learner improvement, semantic grading quality, model
lift, production OS isolation, target hardware, or online reinforcement
learning.

## P0: one evidence truth source

- Academy no longer stores mastery or completed nodes in browser
  `localStorage`.
- Clicking a route node, adding a knowledge item, or resolving a mistake cannot
  directly increase mastery.
- The learning dashboard, due queue, quiz selection, and route completion all
  derive from persisted backend evidence.
- Quiz answers are not disclosed before submission. Answers shorter than the
  minimum evidence boundary are rejected.
- Assessment attempts persist their rubric result, model state before and
  after, evidence digest, and next review.
- The Academy UI consumes the backend dashboard and assessment APIs.

## P1: explainable learning and coding evidence

- `bkt-fsrs-lite.v1` maintains `p_known`, stability, difficulty, review count,
  and review timing for each enrolled topic.
- Mastery requires both the configured probability threshold and at least two
  independent evidence records.
- Low-scoring attempts create an explicit mistake. Resolving a mistake changes
  workflow state only; it does not change mastery without a new assessment or
  project artifact.
- Each mastery explanation returns the threshold, probability, algorithm
  version, next review, assessment history, and coding project evidence.
- Coding project evidence must reference a succeeded canonical TaskRun and a
  SHA-256 artifact digest that is present in that TaskRun's durable evidence.
  Duplicate task/artifact evidence is idempotent.
- Context snapshots persist selected sources, budget, trust policy, omitted
  candidates, and decision dependencies.
- Coding reviews support working-tree, base-branch, commit, and pull-request
  scopes with digest-bound findings and tests. Context and review entries are
  visible through one TaskRun ledger.

## P2: governed course extensibility

- Course authors can create draft courses with sourced topics, explicit
  prerequisites, and mastery thresholds.
- Questions require a source, at least two rubric concepts, a cognitive level,
  and bounded difficulty.
- Publication fails closed unless every topic is sourced and assessed, all
  prerequisites exist, the prerequisite graph is acyclic, and thresholds are
  valid.
- Course creation, question authoring, publication, project evidence, and
  mistake resolution require explicit confirmation at the API boundary where
  they mutate governed state.
- Preference Ranker, deep Router, Trajectory RL, behavior LoRA, and online RL
  remain behind their existing real-data gates.

## Main APIs

- `GET /api/academy/learning/courses`
- `POST /api/academy/learning/courses`
- `POST /api/academy/learning/enroll`
- `GET /api/academy/learning/dashboard`
- `GET /api/academy/learning/quiz`
- `POST /api/academy/learning/questions/{question_id}/answers`
- `GET /api/academy/learning/mistakes`
- `POST /api/academy/learning/mistakes/{mistake_id}/resolve`
- `GET /api/academy/learning/items/{item_id}/explain`
- `POST /api/academy/learning/project-evidence`
- `POST /api/academy/learning/courses/{course_id}/questions`
- `GET /api/academy/learning/courses/{course_id}/publish-validation`
- `POST /api/academy/learning/courses/{course_id}/publish`
- `GET /api/agent-product/task-runs/{task_id}/ledger`
- `POST /api/agent-product/task-runs/{task_id}/reviews`

## Truth boundary

The deterministic concept rubric is deliberately labeled. It establishes a
reproducible software loop but cannot prove unrestricted semantic correctness
or educational effectiveness. High-stakes grading still requires a reviewed
evaluator. Data-gated personalization and learning algorithms remain inactive
until their independent evidence thresholds are met.
