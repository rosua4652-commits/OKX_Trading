$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== OKX Auto Trader - Dev Mode ===" -ForegroundColor Cyan
$envPath = Join-Path $Root ".env"
$bindHost = "127.0.0.1"
$port = 8080
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if ($line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $k, $v = $line.Split("=", 2)
        $key = $k.Trim().ToUpper()
        $val = $v.Trim()
        if ($key -eq "OAT_PORT" -and $val) { $script:port = [int]$val }
        if ($key -eq "OAT_HOST" -and $val) { $script:bindHost = $val }
        if ($key -eq "OAT_BIND_EXTERNAL" -and $val -match "^(1|true|yes)$") { $script:bindHost = "0.0.0.0" }
    }
}
Write-Host "Backend: http://${bindHost}:$port (host $bindHost)"
Write-Host "Frontend: Vite dev server"
Write-Host ""

function Test-PythonCandidate {
    param([string]$Exe, [string[]]$Args = @())
    $ErrorActionPreference = "Continue"
    $null = & $Exe @($Args + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)")) 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    $venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
    if ((Test-Path $venvPy) -and (Test-PythonCandidate -Exe $venvPy)) {
        return @{ Exe = $venvPy; Args = @() }
    }
    foreach ($c in @(
        @{ Exe = "python"; Args = @() },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "py"; Args = @() }
    )) {
        if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
            if (Test-PythonCandidate -Exe $c.Exe -Args $c.Args) { return $c }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "[ERROR] Python 3.10+ required." -ForegroundColor Red
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
    "cd /d `"$backendDir`" && call `"$activate`" && python -m uvicorn app.main:app --reload --host $bindHost --port $port"
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
