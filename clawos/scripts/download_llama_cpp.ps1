param(
    [string]$InstallDir = "tools\llama.cpp",
    [string]$AssetPattern = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not [System.IO.Path]::IsPathRooted($InstallDir)) {
    $InstallDir = Join-Path $repoRoot $InstallDir
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (Get-ChildItem -LiteralPath $InstallDir -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1) {
    Write-Host "llama-server.exe already present under $InstallDir"
    exit 0
}

$release = Invoke-RestMethod -Headers @{"User-Agent"="ClawOS"} -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
$assets = @($release.assets)
if (-not $AssetPattern) {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $AssetPattern = "(?i)(cuda|cu12).*win.*x64.*\.zip$|win.*x64.*(cuda|cu12).*\.zip$"
    } else {
        $AssetPattern = "(?i)(cpu|openblas).*win.*x64.*\.zip$|win.*x64.*(cpu|openblas).*\.zip$"
    }
}
$asset = $assets | Where-Object { $_.name -match $AssetPattern } | Select-Object -First 1
if (-not $asset) {
    $asset = $assets | Where-Object { $_.name -match "(?i)win.*x64.*\.zip$" } | Select-Object -First 1
}
if (-not $asset) {
    throw "No Windows x64 llama.cpp release asset found in latest release."
}

$zipPath = Join-Path $InstallDir $asset.name
Write-Host "Downloading llama.cpp runtime: $($asset.name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
$extractDir = Join-Path $InstallDir "runtime"
if (Test-Path -LiteralPath $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
$server = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter llama-server.exe | Select-Object -First 1
if (-not $server) {
    throw "Downloaded llama.cpp archive did not contain llama-server.exe"
}
Write-Host "llama-server.exe ready: $($server.FullName)"
