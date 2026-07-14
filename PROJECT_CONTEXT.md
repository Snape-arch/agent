# Project Context

This is the concise handoff source of truth for ClawOS. The complete historical
handoff log through 2026-07-14 is archived in
`clawos/docs/PROJECT_HISTORY_2026-07-14.md`.

## Current state — 2026-07-14

- Active branch: `codex/p0-demo-polish`.
- Current local commit before this hygiene change: `cf98313`, which merges
  `origin/master` at `5c09fef` with the local profile commit `b9e1618`.
- The remote feature branch currently points to `b9e1618`; the local merge
  commit has not been pushed.
- Latest full regression after the merge: `280 tests OK`, `1 skipped`.
- The working local Qwen profile, Chroma/Qwen3 embedding assets, MTClaw route,
  office workflows, Academy surfaces, and five real-evidence chains remain the
  current verified product baseline.
- Competition evidence is `5 / 5` for the repository/public-input campaign.
  Physical target-device acceptance and a consented live enterprise connector
  tenant remain unverified.

## Repository hygiene block — 2026-07-14

Completed:

- Archived the oversized 2,988-line handoff history and replaced this file with
  a concise current-state entry point.
- Removed accidental Sogou Input cache files under the literal repository path
  `%SystemDrive%/` from version control.
- Removed generated `output/` and `tmp/` artifacts from version control while
  retaining the local files for reproducibility and inspection.
- Consolidated ignore rules so all `output/`, `tmp/`, and literal
  `%SystemDrive%/` paths stay local.
- Added `WORKBUDDY_REAL_EMAIL_CONNECTOR_PLAN.md` as the implementation plan for
  the single real IMAP/SMTP connector closure.
- Reverified the complete Qwen3.5 GGUF, Qwen3 embedding, and Qwen3 reranker
  files against their expected SHA256 values, then removed four independent
  Hugging Face `.incomplete` files totaling 8.117 GiB.
- Audited the 1.32 GiB Git blob to local backup commit `c663560`, which contained
  only generated MTClaw runtime files, logs, temporary files, and the model.
  Removed its local-only backup branch and two exact legacy reflog entries,
  then repacked the repository.

Verification:

- `git diff --cached --check`: passed.
- Tracked artifacts under `output/`, `tmp/`, and `%SystemDrive%`: `0`.
- Representative `output/` and `tmp/` files remain present locally and match
  the consolidated ignore rules.
- High-confidence secret scan of staged text: no matches; tracked `.env`,
  database, log, and cache files: `0`.
- Complete model hashes after cleanup match the recorded manifests; remaining
  `.incomplete` files: `0`.
- Git object storage after repack: about 115 MiB; the audited 1.32 GiB model
  blob is no longer present. HEAD and the staged index tree were unchanged by
  object cleanup.
- No product code changed, so the full suite was not rerun for this hygiene-only
  block. The latest code regression remains `280 tests OK`, `1 skipped`.

Known local-only assets:

- `tools/` is about 9.27 GiB and contains the verified local Qwen/embedding/
  reranker assets plus llama.cpp runtime files.
- `clawos/.venv/` is about 1.1 GiB.
- No Hugging Face `.incomplete` files remain under `tools/models`.
- `.git/` is about 115 MiB after the audited repack.

## Immediate handoff order

1. Review and commit the repository-hygiene change; do not include local model,
   database, log, upload, generated report, or runtime files.
2. Push the local merge commit and hygiene commit through the shared PR flow.
3. Give `WORKBUDDY_REAL_EMAIL_CONNECTOR_PLAN.md` to WorkBuddy and implement only
   the email connector (IMAP read + approval-gated SMTP send).
4. Validate the connector with a dedicated test mailbox: read, summarize,
   action extraction, approval, actual send, SMTP acceptance receipt, failure
   record, and idempotent replay.
5. Rehearse the five real-evidence chains on the competition device.

## Persistent operating rules

- Read this file and `README.md` before broad analysis or code changes.
- Treat `PROJECT_CONTEXT.md` as current state; use the archived history only
  when investigating an older decision.
- Never commit `.env`, credentials, databases, logs, caches, uploads, model
  weights, generated reports, or temporary browser evidence.
- Full tests can mutate `clawos/skills/skill_registry.jsonl`; restore that known
  usage-count side effect before staging.
- External sending, calendar publishing, Git push, PR changes, and other shared
  side effects require explicit user approval and auditable confirmation.
- Do not claim production, enterprise, target-device, or live-tenant readiness
  without matching real evidence.
