# Project Context

This is the concise handoff source of truth for ClawOS. The complete historical
handoff log through 2026-07-14 is archived in
`clawos/docs/PROJECT_HISTORY_2026-07-14.md`.

## Current state — 2026-07-15

- Active branch: `codex/p0-demo-polish`.
- Current local commit: `68c1a30`; the locally known
  `origin/codex/p0-demo-polish` points to the same commit.
- Latest full regression after the merge: `280 tests OK`, `1 skipped`.
- The working local Qwen profile, Chroma/Qwen3 embedding assets, MTClaw route,
  office workflows, Academy surfaces, and five real-evidence chains remain the
  current verified product baseline.
- Competition evidence is `5 / 5` for the repository/public-input campaign.
  Physical target-device acceptance and a consented live enterprise connector
  tenant remain unverified.

## Feishu connector draft review — 2026-07-15

- WorkBuddy has produced an uncommitted Feishu connector draft covering the
  service, client, fake client, server routes, console surface, migration entry,
  and 15 focused tests.
- Focused verification passed: `15` Feishu tests, `42` frontend static tests,
  Python AST parsing, Node syntax, and `git diff --check` before the plan update.
- Review found blocking gaps in the draft: invalid real approval-instance
  parameters, no verification of the actual approver, unauthenticated HTTP
  event ingestion, a non-official and unstarted long-connection transport,
  missing outbound-target enforcement, and incomplete concurrent-send recovery.
- `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md` is now the v2 remediation and live
  acceptance specification. `FEISHU_LIVE` must remain disabled until its
  automated gates pass and the user explicitly authorizes test-tenant access.
- No real Feishu tenant, approval instance, message receipt, or outbound send
  has been verified yet.

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
- Added `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md` as the implementation plan for
  the single real Feishu message-and-approval connector closure.
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

1. Preserve the current uncommitted WorkBuddy draft and unrelated local changes;
   do not reset, overwrite, or stage the skill-registry usage-count side effect.
2. Give `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md` to WorkBuddy and execute its
   Phase 0 through Phase 6 in order, starting with failing regression tests for
   every identified blocker.
3. Keep `FEISHU_LIVE=false` while fixing event trust, approval identity, target
   whitelist, full snapshot hashing, transaction-level idempotency, and recovery.
4. Run focused tests and the full regression, then review the resulting diff
   before any commit or push.
5. Only after explicit user approval, validate in a dedicated Feishu test tenant:
   reject once, attempt an unauthorized approval once, approve once with an
   authorized user, send once, and prove replay/restart does not duplicate it.
6. Rehearse the five real-evidence chains on the competition device.

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
