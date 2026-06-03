function Read-OatDotEnv {
    param([string]$Path)
    $result = @{
        OAT_PORT = 8080
        OAT_HOST = "127.0.0.1"
        OAT_BIND_EXTERNAL = $false
    }
    if (-not (Test-Path $Path)) { return $result }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $k, $v = $line.Split("=", 2)
        $key = $k.Trim().ToUpper()
        $val = $v.Trim().Trim('"').Trim("'")
        switch ($key) {
            "OAT_PORT" { if ($val) { $result.OAT_PORT = [int]$val } }
            "OAT_HOST" { if ($val) { $result.OAT_HOST = $val } }
            "OAT_BIND_EXTERNAL" {
                $result.OAT_BIND_EXTERNAL = $val -match "^(1|true|yes|on)$"
            }
        }
    }
    if ($result.OAT_BIND_EXTERNAL -and $result.OAT_HOST -eq "127.0.0.1") {
        $result.OAT_HOST = "0.0.0.0"
    }
    return $result
}

function Stop-OatServerOnPort {
    param([int]$Port)
    $killed = @()
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            $procId = $c.OwningProcess
            if ($procId -and $procId -notin $killed) {
                Write-Host "Stopping PID $procId (port $Port) ..."
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $killed += $procId
            }
        }
    }
    if (-not $killed.Count) {
        $lines = netstat -ano | Select-String "LISTENING" | Select-String ":$Port\s"
        foreach ($line in $lines) {
            if ($line -match "\s+(\d+)\s*$") {
                $procId = [int]$Matches[1]
                if ($procId -gt 0 -and $procId -notin $killed) {
                    Write-Host "Stopping PID $procId (port $Port) ..."
                    taskkill /PID $procId /F 2>$null | Out-Null
                    $killed += $procId
                }
            }
        }
    }
    if ($killed.Count) {
        Write-Host "Stopped $($killed.Count) process(es)."
    } else {
        Write-Host "No process listening on port $Port."
    }
    return $killed.Count
}

function Initialize-OatLogFiles {
    param([string]$LogDir)
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $sessionLog = Join-Path $LogDir "oat_$stamp.log"
    $latestLog = Join-Path $LogDir "oat-latest.log"
    $dailyLog = Join-Path $LogDir ("oat_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
    $header = "=== OKX Auto Trader $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
    Set-Content -Path $latestLog -Value $header -Encoding UTF8
    Add-Content -Path $sessionLog -Value $header -Encoding UTF8
    Add-Content -Path $dailyLog -Value $header -Encoding UTF8
    return @{
        Session = $sessionLog
        Latest = $latestLog
        Daily = $dailyLog
        All = @($sessionLog, $latestLog, $dailyLog)
    }
}

function Write-OatLogLine {
    param(
        [string]$Line,
        [string[]]$LogFiles
    )
    foreach ($f in $LogFiles) {
        Add-Content -LiteralPath $f -Value $Line -Encoding UTF8
    }
}
