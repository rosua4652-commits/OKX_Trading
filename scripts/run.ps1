$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== OKX Auto Trader ===" -ForegroundColor Cyan
Write-Host ""

function Get-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return @{ Exe = "py"; Args = @("-3") } }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @{ Exe = "python"; Args = @() } }
    return $null
}

$py = Get-Python
if (-not $py) {
    Write-Host "[ERROR] Python 3.10+ is required." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

& $py.Exe @($py.Args + @("--version")) | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python is not working." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host ".env created from .env.example"
        Write-Host "Add OKX API keys to .env, then run again."
        Read-Host "Press Enter to exit"
        exit 1
    }
}

$port = 8080
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $k, $v = $line.Split("=", 2)
        if ($k.Trim().ToUpper() -eq "OAT_PORT" -and $v.Trim()) {
            $script:port = [int]$v.Trim()
        }
    }
}

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python venv ..."
    & $py.Exe @($py.Args + @("-m", "venv", "backend\.venv"))
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Host "Installing backend packages ..."
& $venvPython -m pip install -q -r (Join-Path $Root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { exit 1 }

$distIndex = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] npm not found. Install Node.js 18+." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Building frontend ..."
    Push-Location (Join-Path $Root "frontend")
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    Pop-Location
}

Write-Host ""
Write-Host "Server: http://127.0.0.1:$port"
Write-Host "Stop: Ctrl+C"
Write-Host ""

Set-Location (Join-Path $Root "backend")
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $port
