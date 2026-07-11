param(
    [string]$ManifestPath = "clawos\models\qwen3_5_9b_q4_k_m.json",
    [string]$Proxy = "",
    [switch]$Force,
    [switch]$SkipHash
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not [System.IO.Path]::IsPathRooted($ManifestPath)) {
    $ManifestPath = Join-Path $repoRoot $ManifestPath
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Model manifest not found: $ManifestPath"
}

$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$localPath = [string]$manifest.local_path
if (-not [System.IO.Path]::IsPathRooted($localPath)) {
    $localPath = Join-Path $repoRoot $localPath
}
$isRepositoryBundle = -not $manifest.filename -and [int64]$manifest.model_safetensors_size_bytes -gt 0
if ($isRepositoryBundle) {
    $modelDir = $localPath
    $filename = "model.safetensors"
    $modelPath = Join-Path $modelDir $filename
    $expectedSize = [int64]$manifest.model_safetensors_size_bytes
    $expectedHash = [string]$manifest.model_safetensors_sha256
} else {
    $modelPath = $localPath
    $modelDir = Split-Path -Parent $modelPath
    $filename = [string]$manifest.filename
    $expectedSize = [int64]$manifest.size_bytes
    $expectedHash = [string]$manifest.sha256
}
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

$requiredBundleFiles = @("config.json", "tokenizer_config.json", "tokenizer.json")
if ([string]$manifest.id -match "embedding") {
    $requiredBundleFiles += @("modules.json", "1_Pooling\config.json")
}

function Test-ModelFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path
    if ($expectedSize -gt 0 -and $item.Length -ne $expectedSize) { return $false }
    if (-not $SkipHash -and $expectedHash) {
        $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($hash -ne $expectedHash.ToUpperInvariant()) { return $false }
    }
    return $true
}

function Test-BundleMetadata {
    if (-not $isRepositoryBundle) { return $true }
    foreach ($relativePath in $requiredBundleFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $modelDir $relativePath))) { return $false }
    }
    return $true
}

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
$hf = Join-Path $repoRoot "clawos\.venv\Scripts\hf.exe"
if ($isRepositoryBundle -and (-not (Test-BundleMetadata) -or $Force)) {
    if (-not (Test-Path -LiteralPath $hf)) {
        throw "Repository model metadata is incomplete and clawos\.venv\Scripts\hf.exe is unavailable."
    }
    Write-Host "Syncing Qwen repository metadata: $($manifest.repo_id)"
    $previousDisableXet = $env:HF_HUB_DISABLE_XET
    $env:HF_HUB_DISABLE_XET = "1"
    try {
        & $hf download $manifest.repo_id --exclude $filename --local-dir $modelDir --max-workers 4
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally {
        $env:HF_HUB_DISABLE_XET = $previousDisableXet
    }
}

if (-not $Force -and (Test-ModelFile -Path $modelPath) -and (Test-BundleMetadata)) {
    Write-Host "Qwen model already present and verified: $modelPath"
    exit 0
}

Write-Host "Downloading Qwen model: $($manifest.repo_id)/$filename"
Write-Host "Target: $modelPath"
$url = "https://huggingface.co/$($manifest.repo_id)/resolve/main/$filename"
if ($curl) {
    $curlArgs = @("-L")
    if (-not $Force) { $curlArgs += @("-C", "-") }
    if ($Proxy) { $curlArgs += @("--proxy", $Proxy) }
    $curlArgs += @("--retry", "20", "--retry-all-errors", "--retry-delay", "5", "--connect-timeout", "30", "-o", $modelPath, $url)
    & $curl.Source @curlArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} elseif (Test-Path -LiteralPath $hf) {
    $hfArgs = @("download", [string]$manifest.repo_id, $filename, "--local-dir", $modelDir)
    if ($Force) { $hfArgs += "--force-download" }
    & $hf @hfArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    throw "Neither curl.exe nor clawos\.venv\Scripts\hf.exe is available for model download."
}

if (-not (Test-ModelFile -Path $modelPath) -or -not (Test-BundleMetadata)) {
    throw "Downloaded model failed size/hash verification: $modelPath"
}
Write-Host "Qwen model ready: $modelPath"
