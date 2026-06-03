param([switch]$Log)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$common = Join-Path $PSScriptRoot "oat-env.ps1"
if (-not (Test-Path $common)) {
    Write-Host "[ERROR] Missing $common" -ForegroundColor Red
    Wait-Exit 1
}
. $common

function Wait-Exit {
    param([int]$Code = 0)
    Read-Host "Press Enter to exit"
    exit $Code
}

function Invoke-Quiet {
    param([scriptblock]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Command
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

function Test-PortFree {
    param([int]$Port)
    $ErrorActionPreference = "Continue"
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($inUse) { return $false }
    }
    $hit = netstat -ano | Select-String "LISTENING" | Select-String ":$Port\s"
    return -not $hit
}

function Find-FreePort {
    param([int]$StartPort)
    for ($p = $StartPort; $p -le ($StartPort + 20); $p++) {
        if (Test-PortFree -Port $p) { return $p }
    }
    return $null
}

function Show-PortOwner {
    param([int]$Port)
    $lines = netstat -ano | Select-String ":$Port\s"
    if ($lines) {
        Write-Host "Port $Port is used by:"
        foreach ($line in $lines) {
            Write-Host "  $line"
        }
    }
}

function Get-LanIPv4 {
    try {
        $addrs = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.PrefixOrigin -ne "WellKnown" -and
                $_.IPAddress -notlike "169.254.*"
            } |
            Select-Object -ExpandProperty IPAddress -First 3
        return $addrs
    } catch {
        return @()
    }
}

function Ensure-FirewallRule {
    param([int]$Port)
    $ruleName = "OKX Auto Trader TCP $Port"
    try {
        $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "Firewall: rule already exists ($ruleName)"
            return
        }
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -ErrorAction Stop | Out-Null
        Write-Host "Firewall: opened inbound TCP $Port ($ruleName)" -ForegroundColor Green
    } catch {
        Write-Host "Firewall: could not add rule (try 'Run as administrator'): $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  Or allow TCP port $Port manually in Windows Defender Firewall."
    }
}

Write-Host "=== OKX Auto Trader ===" -ForegroundColor Cyan
Write-Host ""

function Test-PythonCandidate {
    param([string]$Exe, [string[]]$Args = @())
    $ErrorActionPreference = "Continue"
    $null = & $Exe @($Args + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)")) 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    $venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        if (Test-PythonCandidate -Exe $venvPy) {
            return @{ Exe = $venvPy; Args = @(); Label = "venv" }
        }
    }

    $candidates = @(
        @{ Exe = "python"; Args = @(); Label = "python" },
        @{ Exe = "python3"; Args = @(); Label = "python3" },
        @{ Exe = "py"; Args = @("-3"); Label = "py -3" },
        @{ Exe = "py"; Args = @(); Label = "py" }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        if (Test-PythonCandidate -Exe $c.Exe -Args $c.Args) {
            return @{ Exe = $c.Exe; Args = $c.Args; Label = $c.Label }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "[ERROR] Python 3.10+ not found or not working." -ForegroundColor Red
    Write-Host "Install from https://www.python.org/downloads/ and check 'Add python to PATH'."
    Write-Host "Then run: python --version"
    Wait-Exit 1
}

Write-Host "Using Python: $($py.Label) ($($py.Exe))"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host ".env created from .env.example"
        Write-Host "Add OKX API keys to .env, then run again."
        Wait-Exit 1
    }
}

$envCfg = Read-OatDotEnv -Path (Join-Path $Root ".env")
$port = $envCfg.OAT_PORT
$bindHost = $envCfg.OAT_HOST

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python venv ..."
    if ((Invoke-Quiet { & $py.Exe @($py.Args + @("-m", "venv", "backend\.venv")) }) -ne 0) {
        Write-Host "[ERROR] Failed to create venv." -ForegroundColor Red
        Wait-Exit 1
    }
}

Write-Host "Installing backend packages ..."
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $venvPython -m pip install -q -r (Join-Path $Root "backend\requirements.txt") 2>&1 | ForEach-Object {
    $t = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { "$_" }
    if ($t -match '^\[notice\]' -or [string]::IsNullOrWhiteSpace($t)) { return }
    Write-Host $t
}
$ErrorActionPreference = $prev
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed." -ForegroundColor Red
    Wait-Exit 1
}

Get-ChildItem (Join-Path $Root "backend") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

$distIndex = Join-Path $Root "frontend\dist\index.html"
$feRoot = Join-Path $Root "frontend"
$needFeBuild = -not (Test-Path $distIndex)
if (-not $needFeBuild -and (Test-Path $feRoot)) {
    $distJs = Get-ChildItem (Join-Path $feRoot "dist\assets\*.js") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $srcNewest = Get-ChildItem (Join-Path $feRoot "src") -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($srcNewest -and $distJs -and $srcNewest.LastWriteTime -gt $distJs.LastWriteTime) {
        $needFeBuild = $true
    }
}
if ($needFeBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] npm not found. Install Node.js 18+." -ForegroundColor Red
        Wait-Exit 1
    }
    Write-Host "Building frontend ..."
    Push-Location $feRoot
    if (-not (Test-Path "node_modules")) {
        if ((Invoke-Quiet { npm install }) -ne 0) {
            Pop-Location
            Write-Host "[ERROR] npm install failed." -ForegroundColor Red
            Wait-Exit 1
        }
    }
    if ((Invoke-Quiet { npm run build }) -ne 0) {
        Pop-Location
        Write-Host "[ERROR] npm run build failed." -ForegroundColor Red
        Wait-Exit 1
    }
    Pop-Location
}

$preferredPort = $port
if (-not (Test-PortFree -Port $port)) {
    Write-Host "Port $port is busy."
    Show-PortOwner -Port $port
    $free = Find-FreePort -Port ($port + 1)
    if ($free) {
        Write-Host "Using free port $free instead. Set OAT_PORT=$free in .env to keep it."
        $port = $free
    } else {
        Write-Host "[ERROR] No free port between $($preferredPort + 1) and $($preferredPort + 20)." -ForegroundColor Red
        Write-Host "Close the old server window (Ctrl+C) or end the PID shown above."
        Wait-Exit 1
    }
}

if ($bindHost -eq "0.0.0.0") {
    Ensure-FirewallRule -Port $port
}

Write-Host ""
Write-Host "Local:   http://127.0.0.1:$port"
if ($bindHost -eq "0.0.0.0") {
    $lan = Get-LanIPv4
    if ($lan) {
        foreach ($ip in $lan) {
            Write-Host "LAN:     http://${ip}:$port"
        }
    } else {
        Write-Host "LAN:     http://<this-PC-IP>:$port  (ipconfig 로 IPv4 확인)"
    }
    Write-Host "External: bind 0.0.0.0 — no login; do not expose to public internet without VPN." -ForegroundColor Yellow
} else {
    Write-Host "External: disabled (set OAT_BIND_EXTERNAL=1 in .env)"
}
Write-Host "Stop: Ctrl+C"
if ($Log) {
    $logDir = Join-Path $Root "logs"
    $logInfo = Initialize-OatLogFiles -LogDir $logDir
    Write-Host "Log files:" -ForegroundColor Cyan
    Write-Host "  Session: $($logInfo.Session)"
    Write-Host "  Latest:  $($logInfo.Latest)"
    Write-Host "  Daily:   $($logInfo.Daily)"
}
Write-Host ""

Set-Location (Join-Path $Root "backend")
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"

if ($Log) {
    $logFiles = $logInfo.All
    & $venvPython -m uvicorn app.main:app --host $bindHost --port $port 2>&1 | ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { "$_" }
        Write-Host $line
        Write-OatLogLine -Line $line -LogFiles $logFiles
    }
} else {
    & $venvPython -m uvicorn app.main:app --host $bindHost --port $port
}
$ErrorActionPreference = $prev

exit 0
