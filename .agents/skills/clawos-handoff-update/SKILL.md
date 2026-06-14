---
name: clawos-handoff-update
description: Use when finishing a development block in this repository, handing work to another Codex or teammate, updating shared progress notes, or recording tests and next steps.
---

# ClawOS Handoff Update

Use this skill before ending a meaningful development block.

## Required Handoff File

Update:

```text
PROJECT_CONTEXT.md
```

Keep it concise and useful for the next agent.

## What To Update

Add or revise:

- latest completed development block
- files or modules changed
- tests run and exact result
- known warnings or non-blocking issues
- current risks
- recommended next step

Do not record:

- API keys
- passwords
- private tokens
- long command logs
- speculative claims without verification

## Verification Before Handoff

Run at least:

```powershell
git status --short --branch
git diff --name-only
```

If code changed, run the relevant tests. For full ClawOS validation:

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

## Handoff Summary Template

Use this shape in the final response:

```text
已完成：
- ...

验证：
- ...

当前状态：
- ...

下一步：
- ...
```

## Common Mistakes

- Saying work is complete without a fresh test result.
- Leaving `PROJECT_CONTEXT.md` stale.
- Forgetting to mention uncommitted files.
- Including secrets in the handoff.
