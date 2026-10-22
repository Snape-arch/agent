param(
    [string]$ModelPath = "tools\models\qwen3.5-9b-gguf\Qwen3.5-9B-Q4_K_M.gguf",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [int]$ContextSize = 8192,
    [int]$Parallel = 1,
    [string]$GpuLayers = "20",
    [string]$ServerPath = "",
    [switch]$Download
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not [System.IO.Path]::IsPathRooted($ModelPath)) {
    $ModelPath = Join-Path $repoRoot $ModelPath
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
    if ($Download) {
        & (Join-Path $PSScriptRoot "download_qwen_model.ps1")
    } else {
        throw "Qwen GGUF model not found: $ModelPath. Run download_qwen_model.ps1 first, or rerun this script with -Download."
    }
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "Qwen GGUF model not found after download: $ModelPath"
}

$candidates = @()
if ($ServerPath) { $candidates += $ServerPath }
$candidates += @(
    (Join-Path $repoRoot "tools\llama.cpp\llama-server.exe"),
    (Join-Path $repoRoot "tools\llama.cpp\build\bin\Release\llama-server.exe"),
    "llama-server.exe"
)

$server = $null
foreach ($candidate in $candidates) {
    if ($candidate -eq "llama-server.exe") {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { $server = $cmd.Source; break }
    } elseif (Test-Path -LiteralPath $candidate) {
        $server = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}
if (-not $server) {
    $runtimeRoot = Join-Path $repoRoot "tools\llama.cpp"
    $found = Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $server = $found.FullName }
}
if (-not $server -and $Download) {
    & (Join-Path $PSScriptRoot "download_llama_cpp.ps1")
    $runtimeRoot = Join-Path $repoRoot "tools\llama.cpp"
    $found = Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Filter llama-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $server = $found.FullName }
}
if (-not $server) {
    throw "llama-server.exe not found. Put llama.cpp server under tools\llama.cpp, install it on PATH, or pass -ServerPath."
}

Write-Host "Starting Qwen local OpenAI-compatible server"
Write-Host "Model: $ModelPath"
Write-Host "URL:   http://$HostName`:$Port/v1"
$originalModelPath = $env:PATH
try {
    # Some installations keep CUDA companion DLLs under runtime/ while the
    # executable is in its parent. Give this child process that local path.
    $runtimeDir = Join-Path (Split-Path -Parent $server) 'runtime'
    if (Test-Path -LiteralPath $runtimeDir) { $env:PATH = "$runtimeDir;$env:PATH" }
    & $server -m $ModelPath --host $HostName --port $Port -c $ContextSize -np $Parallel -ngl $GpuLayers
} finally {
    $env:PATH = $originalModelPath
}
