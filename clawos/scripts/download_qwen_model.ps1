param(
    [string]$ManifestPath = "clawos\models\qwen3_5_9b_q4_k_m.json",
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
$modelPath = $manifest.local_path
if (-not [System.IO.Path]::IsPathRooted($modelPath)) {
    $modelPath = Join-Path $repoRoot $modelPath
}
$modelDir = Split-Path -Parent $modelPath
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

function Test-ModelFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path
    if ([int64]$manifest.size_bytes -gt 0 -and $item.Length -ne [int64]$manifest.size_bytes) { return $false }
    if (-not $SkipHash -and $manifest.sha256) {
        $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($hash -ne [string]$manifest.sha256) { return $false }
    }
    return $true
}

if (-not $Force -and (Test-ModelFile -Path $modelPath)) {
    Write-Host "Qwen model already present and verified: $modelPath"
    exit 0
}

Write-Host "Downloading Qwen model: $($manifest.repo_id)/$($manifest.filename)"
Write-Host "Target: $modelPath"
$hf = Join-Path $repoRoot "clawos\.venv\Scripts\hf.exe"
if (Test-Path -LiteralPath $hf) {
    & $hf download $manifest.repo_id $manifest.filename --local-dir $modelDir
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    $url = "https://huggingface.co/$($manifest.repo_id)/resolve/main/$($manifest.filename)"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        throw "Neither clawos\.venv\Scripts\hf.exe nor curl.exe is available for model download."
    }
    & $curl.Source -L -C - --retry 8 --retry-delay 5 --connect-timeout 30 -o $modelPath $url
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-ModelFile -Path $modelPath)) {
    throw "Downloaded model failed size/hash verification: $modelPath"
}
Write-Host "Qwen model ready: $modelPath"
