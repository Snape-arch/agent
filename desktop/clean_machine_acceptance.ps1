param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [string]$Report = "$env:TEMP\clawos-clean-machine-acceptance.json",
    [switch]$KeepInstalled
)

$ErrorActionPreference = "Stop"
$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $checks.Add([ordered]@{ name=$Name; passed=$Passed; detail=$Detail })
    if (-not $Passed) { throw "$Name failed: $Detail" }
}

$Installer = (Resolve-Path $Installer).Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\ClawOS"
$DataDir = Join-Path $env:LOCALAPPDATA "ClawOS"
$started = $null
$uiProcesses = @()
try {
    Add-Check "installer_exists" (Test-Path $Installer -PathType Leaf) $Installer
    $hash = (Get-FileHash $Installer -Algorithm SHA256).Hash
    $signature = Get-AuthenticodeSignature $Installer
    $install = Start-Process $Installer -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-" -Wait -PassThru
    Add-Check "silent_install" ($install.ExitCode -eq 0) "exit=$($install.ExitCode)"
    Add-Check "desktop_executable" (Test-Path "$InstallDir\ClawOS.exe") "$InstallDir\ClawOS.exe"
    Add-Check "portable_runtime" (Test-Path "$InstallDir\runtime\pythonw.exe") "$InstallDir\runtime\pythonw.exe"
    Add-Check "no_packaged_secret" (-not (Test-Path "$InstallDir\app\clawos\.env")) "payload excludes .env"
    $databases = @(Get-ChildItem "$InstallDir\app" -Recurse -File -Filter *.db -ErrorAction SilentlyContinue)
    Add-Check "no_packaged_database" ($databases.Count -eq 0) "payload excludes databases"

    $started = Start-Process "$InstallDir\ClawOS.exe" -ArgumentList "--smoke-test=30" -PassThru
    $deadline = (Get-Date).AddSeconds(90)
    $health = $null
    while ((Get-Date) -lt $deadline -and -not $health) {
        try { $health = Invoke-RestMethod "http://127.0.0.1:18790/health" -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 500 }
    }
    Add-Check "no_terminal_start" ($null -ne $health) "desktop executable launched hidden services"
    Add-Check "health_contract" ($health.status -eq "ok") "status=$($health.status)"
    Add-Check "mtclaw_health" ($health.mtclaw.enabled -eq $true -and $health.mtclaw.reachable -eq $true) "enabled=$($health.mtclaw.enabled); reachable=$($health.mtclaw.reachable)"
    Add-Check "user_data_created" (Test-Path $DataDir) $DataDir
    $console = Invoke-WebRequest "http://127.0.0.1:18790/console" -UseBasicParsing -TimeoutSec 5
    Add-Check "console_render_entry" ($console.StatusCode -eq 200 -and $console.Content -match "ClawOS") "http=$($console.StatusCode)"
    Wait-Process -Id $started.Id -Timeout 45
    $started.Refresh()
    Add-Check "clean_shutdown" ($started.HasExited -and $started.ExitCode -eq 0) "exit=$($started.ExitCode)"

    $null = Start-Process "$InstallDir\ClawOS.exe"
    $windowDeadline = (Get-Date).AddSeconds(90)
    $uiProcess = $null
    while ((Get-Date) -lt $windowDeadline -and -not $uiProcess) {
        Start-Sleep -Milliseconds 500
        $uiProcesses = @(Get-Process -Name ClawOS -ErrorAction SilentlyContinue)
        $uiProcess = $uiProcesses | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "ClawOS" } | Select-Object -First 1
    }
    Add-Check "desktop_window" ($null -ne $uiProcess) "native top-level window title=ClawOS"
    $null = $uiProcess.CloseMainWindow()
    $windowCloseDeadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        try { $stillHealthy = Invoke-RestMethod "http://127.0.0.1:18790/health" -TimeoutSec 1 } catch { $stillHealthy = $null }
    } while ((Get-Date) -lt $windowCloseDeadline -and $stillHealthy)
    Add-Check "window_clean_shutdown" ($null -eq $stillHealthy) "closing the window reclaimed ClawOS and MTClaw"

    [ordered]@{
        schema="clawos.desktop.acceptance.v1"; generated_at=(Get-Date).ToUniversalTime().ToString("o")
        machine=[ordered]@{ os=[Environment]::OSVersion.VersionString; architecture=$env:PROCESSOR_ARCHITECTURE; user=$env:USERNAME }
        installer=[ordered]@{ path=$Installer; sha256=$hash; signature_status=[string]$signature.Status }
        checks=$checks; passed=$true
        note="Run this script in Windows Sandbox or a clean Windows VM for competition evidence."
    } | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $Report
    Write-Host "PASS: $Report"
}
finally {
    if ($started -and -not $started.HasExited) { Stop-Process -Id $started.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in @(Get-Process -Name ClawOS -ErrorAction SilentlyContinue)) {
        if (-not $process.HasExited) { $null = $process.CloseMainWindow() }
    }
    if (-not $KeepInstalled -and (Test-Path "$InstallDir\unins000.exe")) {
        Start-Process "$InstallDir\unins000.exe" -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait
    }
}
