param([switch]$NoPause)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$common = Join-Path $PSScriptRoot "oat-env.ps1"
if (-not (Test-Path $common)) {
    Write-Host "[ERROR] Missing $common" -ForegroundColor Red
    if (-not $NoPause) { Read-Host "Press Enter to exit" }
    exit 1
}
. $common

$envCfg = Read-OatDotEnv -Path (Join-Path $Root ".env")
$port = $envCfg.OAT_PORT

Write-Host "=== OKX Auto Trader - Stop ===" -ForegroundColor Cyan
Stop-OatServerOnPort -Port $port | Out-Null
Write-Host "Done. Run run.bat or run-with-log.bat to start again."

if (-not $NoPause) {
    Read-Host "Press Enter to exit"
}
