# Windows Isolation, Release Identity, and Recovery Soak

## Scope

This acceptance closes the software and accelerated-test portions of four
production hardening tracks without claiming unavailable external evidence.

## Restricted Token and file boundary

`services/os_sandbox.py` now starts the probe child through
`CreateRestrictedToken`, removes maximum privileges, applies the LUA token
policy, sets Low Mandatory Integrity (`S-1-16-4096`), sanitizes its environment,
and launches it with `CreateProcessAsUserW` (with a
`CreateProcessWithTokenW` fallback).

The Windows probe passed:

- the child wrote inside its Low Integrity sandbox directory;
- a write into the repository root was blocked;
- the test secret was absent from the child environment;
- AppContainer APIs were detected.

The result does **not** prove read isolation. `IsTokenRestricted` is false for
the privilege/LUA-only token, even though the restricted-token creation API was
used. A persistent AppContainer profile is deliberately not created without an
explicit installation grant. Therefore `production_sandbox_ready=false`.

## Authenticated network egress proxy

`services/egress_proxy.py` provides a loopback HTTP/CONNECT proxy with:

- per-run bearer capability authentication;
- explicit host and port allowlists;
- DNS resolution before connection;
- private, loopback, link-local, reserved, multicast, and unspecified address
  rejection in production policy;
- credential-header stripping unless the destination is separately approved;
- request, response, and tunnel byte limits;
- an audit log that excludes credentials and request headers.

The local probe passed authenticated allow, unauthenticated deny,
non-allowlisted deny, private-address deny, credential stripping, and audit
checks. This controls children configured to use the proxy. It is not a
host-level non-bypass guarantee; AppContainer capability rules, WFP, or Windows
Firewall policy is still required.

## Publisher certificate gate

VSIX release now validates that:

- the private key matches the leaf certificate;
- the certificate is currently valid and is not self-signed;
- the leaf is not a CA and contains the Code Signing EKU;
- every certificate signature reaches a self-signed root in the explicitly
  supplied trust bundle.

The package script derives `trusted_publisher` only from this validation. The
standalone `scripts/validate_publisher_certificate.py` command supports secure
certificate intake without logging private-key material. Unit tests prove a
valid test chain is accepted and a mismatched key is rejected.

No CA-issued production publisher certificate was supplied, so
`trusted_publisher=false` and production VSIX distribution remains blocked.

## Multi-worker recovery soak

`scripts/run_multi_worker_recovery_soak.py`:

- uses independent worker processes against one SQLite queue;
- injects a process exit immediately after one durable claim;
- recovers exactly that interrupted task and creates a retry;
- continues adding work while multiple workers drain the queue;
- checks logical completion, duplicate claims, pending work, worker exits, and
  recovery count;
- reads up to 200,000 soak tasks rather than the interactive 200-task page;
- uses a fresh database for each default run.

The accelerated acceptance ran four workers for 10.07 seconds: 64 logical tasks
succeeded, one interrupted task was recovered, there were no duplicate claims,
and the queue drained. `multi_worker_passed=true`.

`multi_hour_passed` requires at least two observed wall-clock hours and remains
false. Run the same command without reducing the default evidence threshold:

```powershell
.\clawos\.venv\Scripts\python.exe -B `
  clawos\scripts\run_multi_worker_recovery_soak.py `
  --duration-seconds 7200 --minimum-hours 2 --workers 8
```

## Remaining production gates

1. Create and install a named AppContainer profile, grant only the sandbox
   directory, and prove both read and write escape denial.
2. Force all child traffic through the broker with AppContainer network
   capabilities or host WFP/Firewall rules, then prove direct-socket bypass is
   denied.
3. Supply a CA-issued Code Signing certificate and approved trust bundle, sign
   the final VSIX, and repeat clean-machine installation.
4. Complete the two-hour-or-longer, eight-worker soak on the release build and
   retain the generated evidence artifact.
