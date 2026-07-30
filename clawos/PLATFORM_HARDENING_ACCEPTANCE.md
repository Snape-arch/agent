# Platform Hardening Acceptance

Date: 2026-07-31

## Outcome

ClawOS now has executable, machine-verifiable evidence for a Windows
process/resource sandbox backend, reproducible VSIX packaging with detached
cryptographic signing, and durable long-task recovery across independent
processes.

This is not a claim of complete production isolation or trusted marketplace
publication.

## Windows OS Backend

`services/os_sandbox.py` implements a real Win32 Job Object backend.

The local probe verified:

- the child process is assigned to the Job Object;
- one-process limit is enforced and a nested process is blocked;
- per-process memory limit and kill-on-job-close flags are installed;
- the child receives an allowlisted environment and the test secret is absent;
- the expected workspace is the child working directory.

The evidence intentionally reports:

- `filesystem_isolated=false`;
- `network_isolated=false`;
- `production_sandbox_ready=false`.

AppContainer/restricted-token filesystem ACLs and brokered network egress remain
the next security layer.

Run:

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\probe_os_sandbox.py
```

## VSIX Packaging and Signature

`services/vsix_release.py` creates deterministic VSIX ZIP metadata and validates
the required VSIX entries, identity, safe paths, and extension main module.

The release script supports an externally supplied publisher key/certificate.
For local acceptance it can create an ephemeral development certificate; the
private key is never written to the repository.

Local evidence:

- two packages produced the same SHA-256 digest;
- RSA-PSS-SHA256 detached signature verified;
- an appended-byte tamper caused verification to fail;
- VS Code CLI installed the package into isolated user-data and extension
  directories and listed `snape-arch.clawos-coding@0.1.0`.

The development certificate remains `trusted_publisher=false`, so
`signed_packaged_ide=false` and production distribution remains blocked.

Run:

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\package_vscode_extension.py `
  --development-signing --code-cli "D:\Microsoft VS Code\bin\code.cmd"
```

## Process-Restart Recovery

`scripts/run_task_recovery_acceptance.py` uses two independent Python
processes and one durable SQLite database:

1. process A starts a repository task, writes a checkpoint, then exits with
   code 73 without task cleanup;
2. process B opens the same database, marks the original interrupted, creates
   a replay task, preserves repository/checkpoint identity, claims the retry,
   and completes it;
3. the original event history retains `task_recovered`.

This proves restart/replay semantics. It does not claim multi-day production
load or distributed-worker failover.

## Learning Gates

The acceptance does not contribute synthetic examples to learning thresholds.
Current product readiness remains:

- `preference_ranker=false`;
- `deep_router=false`;
- `trajectory_rl=false`;
- `behavior_lora=false`;
- `online_rl_claimed=false`.

## Verification

- Focused platform/product/learning regression: 45 tests passed.
- Full repository regression: 400 tests passed, 0 failed.
- Python compilation and VS Code JavaScript syntax checks passed.
- Readiness reports `os_sandbox_backend_probe=true` and
  `process_restart_recovery=true`.
- Readiness remains `product_ready=false` because trusted publisher,
  production filesystem/network sandbox, empirical data, and advanced learning
  gates remain incomplete.
