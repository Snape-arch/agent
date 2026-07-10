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

$hasNvidia = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$existingServer = Get-ChildItem -LiteralPath $InstallDir -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
$existingCudaBackend = Get-ChildItem -LiteralPath $InstallDir -Recurse -Filter "ggml-cuda.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
$existingCudaRuntime = Get-ChildItem -LiteralPath $InstallDir -Recurse -Filter "cudart64*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingServer -and (-not $existingCudaBackend -or $existingCudaRuntime)) {
    Write-Host "llama-server.exe already present under $InstallDir"
    exit 0
}

function Save-ReleaseAsset {
    param($Asset, [string]$Destination)

    Write-Host "Downloading llama.cpp runtime: $($Asset.name)"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L -C - --retry 8 --retry-delay 5 --connect-timeout 30 -o $Destination $Asset.browser_download_url
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } else {
        Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Destination
    }
}

$release = Invoke-RestMethod -Headers @{"User-Agent"="ClawOS"} -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
$assets = @($release.assets)
if (-not $AssetPattern) {
    if ($hasNvidia) {
        $AssetPattern = "(?i)^llama-.*bin-win-(cuda|cu12).*x64\.zip$"
    } else {
        $AssetPattern = "(?i)^llama-.*bin-win-(cpu|openblas).*x64\.zip$"
    }
}
$asset = $assets | Where-Object { $_.name -match $AssetPattern -and $_.name -notmatch "(?i)^cudart-" } | Select-Object -First 1
if (-not $asset) {
    $asset = $assets | Where-Object { $_.name -match "(?i)^llama-.*bin-win-.*x64\.zip$" -and $_.name -notmatch "(?i)^cudart-" } | Select-Object -First 1
}
if (-not $asset) {
    throw "No Windows x64 llama.cpp release asset found in latest release."
}

$extractDir = if ($existingServer) { $existingServer.DirectoryName } else { Join-Path $InstallDir "runtime" }
if (-not $existingServer) {
    $zipPath = Join-Path $InstallDir $asset.name
    Save-ReleaseAsset -Asset $asset -Destination $zipPath
    if (Test-Path -LiteralPath $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
} else {
    Write-Host "llama-server.exe already present; checking companion runtime files."
}

$cudaVersion = $null
if ($asset.name -match "(?i)bin-win-cuda-([0-9.]+)-x64\.zip$") {
    $cudaVersion = $Matches[1]
}
if ($cudaVersion -and -not $existingCudaRuntime) {
    $cudaAsset = $assets | Where-Object { $_.name -match "(?i)^cudart-llama-bin-win-cuda-$([regex]::Escape($cudaVersion))-x64\.zip$" } | Select-Object -First 1
    if (-not $cudaAsset) {
        throw "Matching CUDA runtime archive not found for llama.cpp CUDA $cudaVersion."
    }
    $cudaZipPath = Join-Path $InstallDir $cudaAsset.name
    Save-ReleaseAsset -Asset $cudaAsset -Destination $cudaZipPath
    Expand-Archive -LiteralPath $cudaZipPath -DestinationPath $extractDir -Force
}

$server = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter llama-server.exe | Select-Object -First 1
if (-not $server) {
    throw "Downloaded llama.cpp archive did not contain llama-server.exe"
}
if ($cudaVersion -and -not (Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "cudart64*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    throw "CUDA runtime files are missing after llama.cpp installation."
}
Write-Host "llama-server.exe ready: $($server.FullName)"
