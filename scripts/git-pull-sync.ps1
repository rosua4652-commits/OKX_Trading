param(
    [string]$Branch = "cursor/okx-auto-trader-2696"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$RemoteUrl = "https://github.com/rosua4652-commits/OKX_Trading.git"

Write-Host "=== OKX Auto Trader - Git Pull Sync ===" -ForegroundColor Cyan
Write-Host "Branch: $Branch"
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git not installed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path ".git")) {
    Write-Host "No .git - use update-zip.bat or git-push.bat first."
    Read-Host "Press Enter to exit"
    exit 1
}

$rebaseDir = Join-Path $Root ".git\rebase-merge"
$rebaseApply = Join-Path $Root ".git\rebase-apply"
if ((Test-Path $rebaseDir) -or (Test-Path $rebaseApply)) {
    Write-Host "Aborting interrupted rebase ..."
    git rebase --abort 2>&1 | ForEach-Object { Write-Host $_ }
    git show-ref --verify --quiet "refs/heads/$Branch" 2>$null
    if ($LASTEXITCODE -eq 0) {
        git checkout $Branch 2>&1 | ForEach-Object { Write-Host $_ }
    }
}

$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$origin = git remote get-url origin 2>$null
$ErrorActionPreference = $prev
if (-not $origin) {
    git remote add origin $RemoteUrl
} else {
    git remote set-url origin $RemoteUrl
}

git fetch origin $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] git fetch failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

git show-ref --verify --quiet "refs/heads/$Branch" 2>$null
if ($LASTEXITCODE -eq 0) {
    git checkout $Branch
} else {
    Write-Host "[WARN] No local branch - checkout would use OLD remote files only."
    $ok = Read-Host "Create branch from origin/$Branch anyway? y/N"
    if ($ok -notmatch "^[yY]$") { exit 0 }
    git checkout -b $Branch "origin/$Branch"
}

$local = ""
git rev-parse HEAD 2>$null | ForEach-Object { $local = $_.Trim() }
$remote = ""
git rev-parse "origin/$Branch" 2>$null | ForEach-Object { $remote = $_.Trim() }

Write-Host ""
Write-Host "Local:  $local"
Write-Host "Remote: $remote"
Write-Host ""

Write-Host "[STOP] pull --rebase is disabled in this project." -ForegroundColor Red
Write-Host "It replays commits onto old GitHub files and breaks the folder (missing backtest UI, etc.)."
Write-Host ""
Write-Host "  Keep this PC version  -> restore-local.bat or do nothing"
Write-Host "  Upload this PC to GitHub -> git-push.bat (may ask force-with-lease once)"
Write-Host ""

Read-Host "Press Enter to exit"
