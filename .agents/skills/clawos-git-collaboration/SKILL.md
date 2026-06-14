---
name: clawos-git-collaboration
description: Use when syncing this repository with GitHub, working after another contributor has pushed or merged commits, preparing a branch for review, or checking whether local and remote progress diverged.
---

# ClawOS Git Collaboration

Use this skill for two-person GitHub collaboration.

## Safe Sync Flow

1. Inspect local state:

```powershell
git status --short --branch
git log -5 --oneline --decorate
git branch -vv
```

2. Fetch remote:

```powershell
git fetch origin
```

3. Compare branch against `origin/master`:

```powershell
git rev-list --left-right --count HEAD...origin/master
```

Interpretation:

- `0 N`: local is behind, fast-forward or rebase may be needed.
- `N 0`: local has commits not on master, push or PR may be needed.
- `A B`: branches diverged; inspect before merging.

## Guardrails

- Never overwrite local dirty files.
- Do not use `git reset --hard` unless the user explicitly asks.
- Do not force-push without explicit confirmation.
- If `.env` or secrets appear in status/diff, stop and fix ignore rules before pushing.
- Prefer PR flow for shared changes.

## After Merge

After the user says a PR was merged:

```powershell
git fetch origin
git merge --ff-only origin/master
```

Then update `PROJECT_CONTEXT.md` if the merge changed project state or next steps.

## Final Collaboration Summary

Report:

- branch and latest commit
- ahead/behind status
- dirty files
- tests run and result
- whether `PROJECT_CONTEXT.md` was updated
