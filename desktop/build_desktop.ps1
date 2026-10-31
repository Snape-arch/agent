param([string]$Version = "0.1.0", [switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ClawOS = Join-Path $RepoRoot "clawos"
$Python = Join-Path $ClawOS ".venv\Scripts\python.exe"
$BuildRoot = Join-Path $PSScriptRoot "build"
$Stage = Join-Path $PSScriptRoot "stage"
$Dist = Join-Path $RepoRoot "dist"
if (-not (Test-Path $Python)) { throw "Missing build virtualenv: $Python" }

Remove-Item -Recurse -Force $BuildRoot,$Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $BuildRoot,$Stage,$Dist | Out-Null

Write-Host "[1/6] Creating brand icon"
& $Python -c "from PIL import Image; im=Image.open(r'$ClawOS\static\assets\clawos-mark.png').convert('RGBA'); im.save(r'$BuildRoot\clawos.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

Write-Host "[2/6] Building windowed desktop shell"
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ClawOS --icon (Join-Path $BuildRoot "clawos.ico") `
    --distpath $Stage --workpath (Join-Path $BuildRoot "pyinstaller") `
    --specpath $BuildRoot (Join-Path $PSScriptRoot "clawos_desktop.py")
if ($LASTEXITCODE -ne 0) { throw "Desktop shell build failed" }

Write-Host "[3/6] Assembling portable Python runtime"
$BasePython = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$Runtime = Join-Path $Stage "runtime"
New-Item -ItemType Directory -Force $Runtime,(Join-Path $Runtime "Lib") | Out-Null
Copy-Item "$BasePython\python.exe","$BasePython\pythonw.exe","$BasePython\python3.dll","$BasePython\python312.dll","$BasePython\vcruntime140.dll","$BasePython\vcruntime140_1.dll","$BasePython\LICENSE.txt" $Runtime
Copy-Item -Recurse "$BasePython\DLLs" $Runtime
Get-ChildItem "$BasePython\Lib" | Where-Object { $_.Name -notin @("site-packages","test","tkinter") } | Copy-Item -Destination (Join-Path $Runtime "Lib") -Recurse
Copy-Item -Recurse "$ClawOS\.venv\Lib\site-packages" (Join-Path $Runtime "Lib\site-packages")

Write-Host "[4/6] Copying tracked application payload"
$AppRoot = Join-Path $Stage "app"
$AppClawOS = Join-Path $AppRoot "clawos"
$AppMtClaw = Join-Path $AppRoot "mtclaw-source"
New-Item -ItemType Directory -Force $AppClawOS,$AppMtClaw | Out-Null
$ClawFiles = git -C $RepoRoot -c core.quotepath=false ls-files "clawos/**"
foreach ($relative in $ClawFiles) {
    if ($relative -match '(^|/)(tmp|tools|output|uploads|backups|tests|docs|__pycache__)(/|$)' -or $relative -match '(\.env$|\.db$|\.log$|\.pyc$|\.md$)') { continue }
    $source = Join-Path $RepoRoot $relative
    if (-not (Test-Path $source -PathType Leaf)) { continue }
    $tail = $relative.Substring("clawos/".Length).Replace('/', '\')
    $target = Join-Path $AppClawOS $tail
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item $source $target
}
$VisionFiles = git -C $RepoRoot -c core.quotepath=false ls-files "integrations/clawvision/**"
foreach ($relative in $VisionFiles) {
    if ($relative -match '(^|/)(node_modules|data|output|tests|docs|coverage|__pycache__)(/|$)' -or $relative -match '(\.db$|\.log$|\.pyc$|\.tsbuildinfo$)') { continue }
    $source = Join-Path $RepoRoot $relative
    if (-not (Test-Path $source -PathType Leaf)) { continue }
    $target = Join-Path $AppRoot ($relative.Replace('/', '\'))
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item $source $target
}
$MtFiles = git -C $RepoRoot -c core.quotepath=false ls-files "MTClaw-*/**"
$VisionLibraries = Join-Path $ClawOS "output\vision-libs"
if (Test-Path $VisionLibraries -PathType Container) {
    Copy-Item -Recurse $VisionLibraries (Join-Path $AppRoot "integrations\clawvision\runtime-libs")
}
foreach ($relative in $MtFiles) {
    if ($relative -match '(^|/)(tmp|output|__pycache__)(/|$)' -or $relative -match '(\.env$|\.db$|\.log$|\.pyc$)') { continue }
    $source = Join-Path $RepoRoot $relative
    if (-not (Test-Path $source -PathType Leaf)) { continue }
    $tail = $relative.Substring($relative.IndexOf('/') + 1).Replace('/', '\')
    $target = Join-Path $AppMtClaw $tail
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item $source $target
}

Write-Host "[5/6] Running portable payload preflight"
& (Join-Path $Runtime "python.exe") -c "import fastapi, uvicorn, httpx, openpyxl, fitz; print('portable-runtime-ok')"
if ($LASTEXITCODE -ne 0) { throw "Portable runtime import check failed" }
& (Join-Path $Runtime "python.exe") -m py_compile (Join-Path $AppClawOS "clawos_server.py")
if ($LASTEXITCODE -ne 0) { throw "Packaged server syntax check failed" }

if (-not $SkipInstaller) {
    Write-Host "[6/6] Compiling Windows installer"
    $Iscc = @("$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 not found" }
    & $Iscc "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot "ClawOS.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
}
Write-Host "Desktop package ready: $Stage"
if (-not $SkipInstaller) { Write-Host "Installer: $Dist\ClawOS-Setup-$Version.exe" }
