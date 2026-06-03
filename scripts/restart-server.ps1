param([switch]$NoPause)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== OKX Auto Trader - Restart (with log) ===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "stop-server.ps1") -NoPause
Start-Sleep -Seconds 2
& (Join-Path $PSScriptRoot "run.ps1") -Log

if (-not $NoPause) {
    Read-Host "Press Enter to exit"
}
