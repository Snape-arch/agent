[CmdletBinding()]
param(
    [switch]$InstallDesktopTools,
    [switch]$IncludeLocalAI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvRoot = Join-Path $ProjectRoot ".venv"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = if (Test-Path -LiteralPath $BundledPython) { $BundledPython } else { (Get-Command py -ErrorAction Stop).Source }

if (-not (Test-Path -LiteralPath $VenvRoot)) {
    if ($Python -like "*py.exe") {
        & $Python -3.12 -m venv $VenvRoot
    } else {
        & $Python -m venv $VenvRoot
    }
}

$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-test.txt")
if ($IncludeLocalAI) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
}

if ($InstallDesktopTools) {
    if (-not (Test-Path -LiteralPath "C:\Program Files\LibreOffice\program\soffice.exe")) {
        & winget install --id TheDocumentFoundation.LibreOffice --exact --silent --accept-package-agreements --accept-source-agreements
    }
    if (-not (Get-Command pdftoppm -ErrorAction SilentlyContinue)) {
        $BundledPoppler = Get-ChildItem (Join-Path $env:USERPROFILE ".cache\codex-runtimes") -Recurse -Filter pdftoppm.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $BundledPoppler) {
            & winget install --id oschwartz10612.Poppler --exact --silent --accept-package-agreements --accept-source-agreements
        }
    }
}

& (Join-Path $PSScriptRoot "test_all.ps1") -SkipBootstrap
