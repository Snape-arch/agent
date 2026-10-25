# Windows application runtime

`windows-py312.lock.txt` locks all 141 distributions, including the installer and
transitive dependencies, to the resolved Windows x64 wheels and their SHA-256.
The adjacent JSON records wheel provenance and normalized dependency-input hashes.
This is separate from the smaller CI test environment.

Prepare with an existing Windows x64 CPython 3.12 installation:

```powershell
$appBasePython = & py -3.12 -c "import sys; print(sys.executable)"
& $appBasePython -I clawos/scripts/application_runtime.py prepare --python $appBasePython
```

Preparation creates a new versioned venv in ignored `clawos/output/app-runtimes`;
it never inherits system packages, overwrites an old runtime, edits `.env`,
installs global packages, or copies user data. Downloads use the explicit PyPI
index, wheel-only installation and `--require-hashes`. Child environments omit
model keys, package-index overrides and Python search-path overrides.

Before activation it runs `pip check`, rejects missing/extra/duplicate or external
distributions, imports the actual binary/native dependencies and performs a CPU
tensor operation. It records Python/launcher fingerprints and package versions.
Only then is `current.json` replaced atomically. Failure retains an install log
and state file; an earlier activation is preserved. A single preparation lock
prevents concurrent installs. LF/CRLF checkouts have the same lock identity.

`start_clawos.bat` automatically selects this verified runtime when the activation
exists. Verification failure stops startup. The explicit `CLAWOS_PYTHON` override
remains available for deliberate development use. Without an activation, the
existing development fallback is unchanged.

```powershell
py -3.12 -I clawos/scripts/application_runtime.py selected
py -3.12 -I clawos/scripts/application_runtime.py verify --python <venv-python.exe>
.\start_clawos.bat --check-runtime
```

To update dependencies, review the input versions, then resolve on Windows x64
CPython 3.12 using the explicit public index and no installed-package reuse:

```powershell
py -3.12 -I -m pip --isolated --disable-pip-version-check install --dry-run --ignore-installed --only-binary=:all: --index-url https://pypi.org/simple --report <ignored-report.json> -r clawos/deployment/windows-py312.in
py -3.12 -I clawos/scripts/lock_application_runtime.py <ignored-report.json>
```

Review the lock diff, prepare a new runtime, and repeat real application acceptance
before relying on it. The converter rejects local/VCS/credentialed artifacts and
non-PyPI wheel URLs. It does not select newer versions on application startup.

Scope: web/API, document/PDF/Office libraries, Chroma, local Qwen embeddings,
Feishu SDK, syntax parsers and ASR libraries. Existing model weights, llama.cpp,
LibreOffice, base CPython and optional PaddleOCR remain external. ASR imports do
not prove audio recognition quality or installed ASR weights. No model downloads
occur in preparation. This is an isolated venv, **not a portable bundled Python
distribution**. Wheel hashes verify installation downloads; startup inventory is
not a complete hash attestation of every installed library file.
