# Product Maturity P0-P2 Closure

Date: 2026-07-30

## Outcome

This iteration closes the remaining **software contracts** from the project
assessment. It does not manufacture the external evidence needed for product
readiness.

The unified report deliberately returns:

- `software_contracts_closed=true`
- `product_ready=false`
- `online_rl_claimed=false`

with the current observed local data.

## P0: empirical coding contract

- The paired coding benchmark now accepts only unique, blinded,
  evidence-bound real-repository or user-trajectory cases.
- Baseline and candidate must have different policy identities.
- Every run records hidden-test totals, patch/test digests, latency,
  regression count, rollback, human intervention, safety, and normalized cost.
- Activation requires at least 30 valid cases across at least five
  repositories, positive cluster-bootstrap lift, higher patch success, no
  regression-rate increase, and no candidate safety violations.
- `scripts/run_local_coding_evaluator.py --repo ...` evaluates a real Git
  repository in an isolated, no-hardlink detached clone, preserving the source
  checkout even when the default report directory is inside that repository.
- `scripts/evaluate_coding_outcome_benchmark.py` evaluates and optionally
  persists a paired report. The case schema is
  `benchmarks/coding_outcome_case.schema.json`.

The currently available local evidence remains three controlled fixtures,
zero passes, zero real-repository cases, and zero OPE-eligible decisions.

## P1: reproducible product engineering

- Added a least-privilege GitHub Actions workflow using Python 3.12, exact
  test dependencies, full repository tests, critical compilation, and VS Code
  extension syntax validation.
- Added `services/product_readiness_service.py` and a modular FastAPI router at
  `api/product_readiness.py`; `GET /api/product/readiness` no longer requires
  another top-level route body in the server monolith.
- The VS Code source flow now performs a health preflight, context
  normalization, proposal preview, explicit modal confirmation, checkpointed
  execution, timeout, cancellation, and visible error handling.
- A signed and compatibility-tested VSIX remains an external release artifact,
  so the packaged-IDE check stays false.

## P2: advanced-learning truth boundary

The unified readiness surface consumes observed Agent Learning quality and
keeps each gate separate:

- Preference Ranker
- deep Skill Router
- Trajectory RL
- behavior LoRA

No missing value is converted into readiness. The report never activates or
trains these systems and always returns `online_rl_claimed=false`.

## Commands

```powershell
python clawos/scripts/assess_product_readiness.py
python clawos/scripts/assess_product_readiness.py --strict

python clawos/scripts/run_local_coding_evaluator.py `
  --repo C:\path\to\repo `
  --repository-id project-issue-001 `
  --objective "Fix the selected issue" `
  --hidden-test-json '["python","-m","unittest","-q"]'

python clawos/scripts/evaluate_coding_outcome_benchmark.py `
  --cases C:\path\to\paired-cases.json `
  --confirmed --strict
```

`--strict` exits non-zero while empirical or release evidence remains below
the gate. This is expected until real data, target hardware, and a signed IDE
artifact are available.

## Next evidence, not more framework

1. Use a coding-capable model on 30-50 blinded real-repository issues.
2. Reach 50 complete trajectories and 20 grounded feedback records, then fit
   Reward Calibration.
3. Validate process/filesystem/network containment on target hardware.
4. Package, sign, and compatibility-test the VS Code extension.
5. Revisit Preference/Router/Trajectory RL/LoRA only when their existing data
   gates pass.
