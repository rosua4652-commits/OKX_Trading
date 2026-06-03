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
    Write-Host "No .git — use update-zip.bat or git-push.bat first."
    Read-Host "Press Enter to exit"
    exit 1
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

$hasLocal = $false
git show-ref --verify --quiet "refs/heads/$Branch" 2>$null
if ($LASTEXITCODE -eq 0) { $hasLocal = $true }

if ($hasLocal) {
    git checkout $Branch
} else {
    git checkout -b $Branch "origin/$Branch"
}

$stashNeeded = $false
git diff --quiet 2>$null
$dirty = ($LASTEXITCODE -ne 0)
if ($dirty) {
    Write-Host "Stashing local changes..."
    git stash push -m "oat-sync-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $stashNeeded = $true
}

git pull --rebase origin $Branch
$pullOk = ($LASTEXITCODE -eq 0)

if ($stashNeeded) {
    Write-Host "Restoring stash..."
    git stash pop 2>$null
}

if (-not $pullOk) {
    Write-Host ""
    Write-Host "[ERROR] pull --rebase failed. Resolve conflicts, then git-push.bat" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Synced with origin/$Branch" -ForegroundColor Green
Write-Host "https://github.com/rosua4652-commits/OKX_Trading/tree/$Branch"
Read-Host "Press Enter to exit"
