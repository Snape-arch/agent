# ClawOS Desktop

ClawOS Desktop is a user-level Windows package with a native WebView2 window,
hidden ClawOS/MTClaw services, a dedicated data directory, shortcuts and a
standard uninstaller.

## Build

```powershell
.\clawos\.venv\Scripts\python.exe -m pip install -r .\desktop\requirements-build.txt
.\desktop\build_desktop.ps1
```

Generated outputs are ignored by Git:

- `dist\ClawOS-Setup-0.1.0.exe`
- `desktop\stage\` portable payload
- `desktop\build\` intermediates

The installer excludes `.env`, databases, logs, uploads, `tmp`, `tools`, model
weights and generated output. Mutable state is stored in
`%LOCALAPPDATA%\ClawOS`; the application is installed to
`%LOCALAPPDATA%\Programs\ClawOS` without administrator permission.

## Acceptance

```powershell
.\desktop\clean_machine_acceptance.ps1 -Installer .\dist\ClawOS-Setup-0.1.0.exe
```

For clean-machine evidence, place the installer and acceptance script in the
mapped folder, replace the placeholder in `ClawOS-Clean-Machine.wsb`, and open
the `.wsb` file on a host with Windows Sandbox enabled. The report records the
installer SHA-256, OS identity, startup health, MTClaw reachability, console
entry, data separation and secret/database exclusion.

Only the Windows Sandbox/VM report is clean-machine evidence. A test on the
build machine proves installability but must not be described as clean-machine
proof.

The generated installer is unsigned until a competition/release code-signing
certificate is provided. Its SHA-256 is always captured by the acceptance
report; do not present an unsigned build as a signed production release.
