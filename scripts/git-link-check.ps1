$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Branch = "cursor/okx-auto-trader-2696"
$RemoteUrl = "https://github.com/rosua4652-commits/OKX_Trading.git"

Write-Host "=== Git link check ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Host "[X] No .git folder - not a git repo." -ForegroundColor Red
    Write-Host "    Run git-push.bat once to init and push."
    exit 1
}

$origin = git remote get-url origin 2>$null
if (-not $origin) {
    Write-Host "[!] No origin remote. Adding $RemoteUrl"
    git remote add origin $RemoteUrl
    $origin = $RemoteUrl
}
Write-Host "Remote origin: $origin"
Write-Host "Branch:        $Branch"
Write-Host "Git user:      $(git config user.name) <$(git config user.email)>"
Write-Host ""

git fetch origin $Branch 2>&1 | ForEach-Object { Write-Host $_ }

$local = ""
git rev-parse "refs/heads/$Branch" 2>$null | ForEach-Object { $local = $_.Trim() }
$remote = ""
git rev-parse "refs/remotes/origin/$Branch" 2>$null | ForEach-Object { $remote = $_.Trim() }

if (-not $local) {
    Write-Host "[X] Local branch missing. Checkout or run restore-local.bat" -ForegroundColor Red
    exit 1
}

Write-Host "Local commit:  $local  $(git log -1 --oneline $local)"
if ($remote) {
    Write-Host "Remote commit: $remote  $(git log -1 --oneline $remote)"
    git merge-base --is-ancestor $remote $local 2>$null
    if ($LASTEXITCODE -eq 0) {
        $n = (git rev-list --count "$remote..$local").Trim()
        Write-Host ""
        Write-Host "[OK] Local is $n commit(s) AHEAD of GitHub. Use git-push.bat (force-with-lease if asked)." -ForegroundColor Green
    } else {
        git merge-base --is-ancestor $local $remote 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "[!] GitHub is ahead. Do NOT git-pull-sync. Use restore-local.bat to keep PC files." -ForegroundColor Yellow
        } else {
            Write-Host ""
            Write-Host "[!] Histories differ. git-push.bat -> answer y to force-with-lease once." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "Remote branch: (not on GitHub yet)"
    Write-Host ""
    Write-Host "[OK] First push: git-push.bat" -ForegroundColor Green
}

$dirty = git status --porcelain
if ($dirty) {
    Write-Host ""
    Write-Host "Uncommitted changes (commit before push):" -ForegroundColor Yellow
    git status -sb
}
