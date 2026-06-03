$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== OKX Auto Trader - Dev Mode ===" -ForegroundColor Cyan
Write-Host "Backend: http://127.0.0.1:8080"
Write-Host "Frontend: Vite dev server"
Write-Host ""

function Get-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return @{ Exe = "py"; Args = @("-3") } }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @{ Exe = "python"; Args = @() } }
    return $null
}

$py = Get-Python
if (-not $py) {
    Write-Host "[ERROR] Python required." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $py.Exe @($py.Args + @("-m", "venv", "backend\.venv"))
}

& $venvPython -m pip install -q -r (Join-Path $Root "backend\requirements.txt")

$activate = Join-Path $Root "backend\.venv\Scripts\Activate.ps1"
$backendDir = Join-Path $Root "backend"
Start-Process cmd -ArgumentList @(
    "/k",
    "cd /d `"$backendDir`" && call `"$activate`" && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080"
) -WindowStyle Normal

if (Get-Command npm -ErrorAction SilentlyContinue) {
    $frontendDir = Join-Path $Root "frontend"
    Start-Process cmd -ArgumentList @(
        "/k",
        "cd /d `"$frontendDir`" && npm install && npm run dev"
    ) -WindowStyle Normal
} else {
    Write-Host "npm not found. Install Node.js for frontend dev server."
}

Read-Host "Press Enter to close this window"
