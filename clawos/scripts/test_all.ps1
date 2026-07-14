[CmdletBinding()]
param([switch]$SkipBootstrap)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    if ($SkipBootstrap) { throw "Missing .venv. Run scripts/bootstrap_test_env.ps1 first." }
    & (Join-Path $PSScriptRoot "bootstrap_test_env.ps1")
    exit $LASTEXITCODE
}

$ToolBins = @()
$LibreOffice = "C:\Program Files\LibreOffice\program"
if (Test-Path -LiteralPath (Join-Path $LibreOffice "soffice.exe")) { $ToolBins += $LibreOffice }
if ($env:CLAWOS_POPPLER_BIN -and (Test-Path -LiteralPath (Join-Path $env:CLAWOS_POPPLER_BIN "pdftoppm.exe"))) {
    $ToolBins += $env:CLAWOS_POPPLER_BIN
} elseif (-not (Get-Command pdftoppm -ErrorAction SilentlyContinue)) {
    $BundledPoppler = Get-ChildItem (Join-Path $env:USERPROFILE ".cache\codex-runtimes") -Recurse -Filter pdftoppm.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($BundledPoppler) { $ToolBins += $BundledPoppler.Directory.FullName }
}
if ($ToolBins.Count) { $env:PATH = (($ToolBins -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $env:PATH) }

Push-Location $ProjectRoot
try {
    & $Python scripts\check_test_environment.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m unittest discover -s tests -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python tests\test_frontend_static.py
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
