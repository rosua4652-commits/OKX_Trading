# Download GitHub branch ZIP and update project (no git required).
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Branch = "cursor/okx-auto-trader-2696"
)

$ErrorActionPreference = "Stop"
$repo = "rosua4652-commits/OKX_Trading"
$branchPath = $Branch -replace "/", "-"
$branchEnc = [uri]::EscapeDataString($Branch)
$zipUrl = "https://github.com/$repo/archive/refs/heads/$branchEnc.zip"

Write-Host ""
Write-Host "  OKX Auto Trader - GitHub ZIP update (no git)"
Write-Host "  ============================================"
Write-Host "  Repo: $repo"
Write-Host "  Branch: $Branch"
Write-Host ""

$temp = Join-Path $env:TEMP ("oat-update-" + [guid]::NewGuid().ToString("n"))
$zipPath = Join-Path $temp "repo.zip"
$extractRoot = Join-Path $temp "extract"
New-Item -ItemType Directory -Path $temp -Force | Out-Null

try {
    Write-Host "  Downloading..."
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    Write-Host "  Extracting..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force
    $src = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
    if (-not $src) { throw "ZIP extract failed" }

    $skipNames = @(
        "backend\data",
        "backend\.venv",
        "logs",
        "frontend\node_modules",
        "frontend\dist",
        ".env"
    )

    Write-Host "  Copying (backend\data, .env, logs — not touched)..."
    $allFiles = Get-ChildItem -LiteralPath $src.FullName -Recurse -File
    $copied = 0
    foreach ($f in $allFiles) {
        $rel = $f.FullName.Substring($src.FullName.Length).TrimStart("\", "/")
        $skip = $false
        foreach ($s in $skipNames) {
            if ($rel -ieq $s -or $rel -like ($s + "\*") -or $rel -like ($s + "/*")) {
                $skip = $true
                break
            }
        }
        if ($skip) { continue }
        $dest = Join-Path $RepoRoot $rel
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
        $copied++
    }
    Write-Host "  Files updated: $copied"

    $feRoot = Join-Path $RepoRoot "frontend"
    $pkg = Join-Path $feRoot "package.json"
    if (Test-Path -LiteralPath $pkg) {
        Write-Host "  Building frontend (npm)..."
        Push-Location $feRoot
        try {
            if (-not (Test-Path (Join-Path $feRoot "node_modules"))) {
                Write-Host "    npm install..."
                & npm install
                if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
            }
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
            Write-Host "    frontend\dist OK"
        } finally {
            Pop-Location
        }
    }

    $build = $null
    $modelsPy = Join-Path $RepoRoot "backend\app\models.py"
    if (Test-Path $modelsPy) {
        $t = Get-Content $modelsPy -Raw
        if ($t -match 'OAT_BUILD\s*=\s*"([^"]+)"') { $build = $matches[1] }
    }
    Write-Host ""
    Write-Host "  Done. Build: $build"
    Write-Host "  Next: run-with-log.bat or restart-server.bat"
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "  ERROR: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "  Private repo: download ZIP from GitHub in browser, extract, copy manually."
    Write-Host "  Or use git-pull-sync.bat after git login."
    Write-Host ""
    exit 1
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}

exit 0
