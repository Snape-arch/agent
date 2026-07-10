# MTClaw vendored source provenance

This directory is a vendored source snapshot of the GitHub project described by its own README as **OpenClaw Function Router**, version `1.0.0`, licensed under MIT.

## Local provenance

- Imported into this repository by commit `ca00d98521d0dc78a03fa03752a40e046f19facb` on 2026-06-08.
- ClawOS compatibility fixes were applied by commit `232e40262e1d15ce5d3cf9d45ead906cbb4d7d34` on 2026-06-17.
- This directory is intentionally vendored rather than a Git submodule so the competition package remains reproducible offline.
- The original nested `.git` metadata was not retained, so the exact upstream GitHub URL and upstream commit SHA cannot be reconstructed from this snapshot alone. They must be recorded here from the original clone before public release.

## Snapshot fingerprints

```text
A9489EE18817E318E617AE96F5C2071C2A548F07BC15DB34CAA4A91B8CE2644A  function_router/server.py
C8F4A3449F376AD0743E925D6F6E8578F02933169B0A7C41F7208B2109116A42  pyproject.toml
EA78E21CEAEDFB9AB14EF2BCC75CDC40407DC349C7C252A75D34AA3A0ED3BCF0  README.zh-CN.md
```

## Integration policy

- Keep the upstream MIT `LICENSE` with all distributed copies.
- Prefer ClawOS adapters, generated wrappers, configuration, and tests over direct edits to vendored files.
- Any future direct edit must be recorded below with rationale and regression evidence.
- The competition release gate must report missing upstream URL/SHA as a provenance warning until the original clone metadata is supplied.

## Known local changes

- Session header compatibility and Function Router integration fixes in local commit `232e402`.
- ClawOS-specific vertical tools are implemented outside this vendored directory and exposed through `clawos/mtclaw/bridge_runner.py`.
