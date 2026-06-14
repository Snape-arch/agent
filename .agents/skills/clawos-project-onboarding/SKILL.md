---
name: clawos-project-onboarding
description: Use when starting work in this repository, resuming after another contributor, checking current project status, or deciding what to read before modifying ClawOS code.
---

# ClawOS Project Onboarding

Use this skill to avoid re-reading the whole repository.

## Required First Reads

Read these files before broad analysis or code changes:

1. `PROJECT_CONTEXT.md`
2. `README.md`
3. Only then read the specific module files needed for the requested task.

If the request is about architecture or roadmap, also read:

- `clawos/ROADMAP.md`
- `clawos/ENTERPRISE_READINESS.md`
- `clawos/MTCLAW_INTEGRATION.md`

## Startup Checklist

Run lightweight status checks:

```powershell
git status --short --branch
git log -5 --oneline --decorate
git remote -v
```

Then summarize:

- current branch
- dirty files
- latest commit
- whether local branch appears ahead or behind remote
- what `PROJECT_CONTEXT.md` says is the next step

## Reading Rules

- Do not scan the whole repository unless the task truly requires it.
- Prefer targeted reads around the module being changed.
- Treat `PROJECT_CONTEXT.md` as the shared handoff source of truth.
- If `PROJECT_CONTEXT.md` disagrees with current code, verify with targeted code reads and update the context file after the work.

## Common Mistakes

- Starting by recursively reading every file.
- Ignoring uncommitted teammate work.
- Trusting stale memory instead of current `PROJECT_CONTEXT.md`.
- Forgetting to update `PROJECT_CONTEXT.md` after changing direction.
