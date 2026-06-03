$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Host "[ERROR] Not a git repo: $Root" -ForegroundColor Red
    exit 1
}

$rebaseDir = Join-Path $Root ".git\rebase-merge"
$rebaseApply = Join-Path $Root ".git\rebase-apply"
if ((Test-Path $rebaseDir) -or (Test-Path $rebaseApply)) {
    Write-Host "Aborting interrupted rebase ..."
    git rebase --abort 2>&1 | ForEach-Object { Write-Host $_ }
}

$head = (git rev-parse HEAD 2>$null).Trim()
$branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
$ref = "refs/heads/$branch"
if (git rev-parse $ref 2>$null) {
    $target = (git rev-parse $ref).Trim()
} else {
    $target = $head
}

Write-Host "Branch: $branch"
Write-Host "Reset to: $target"
git reset --hard $target
git status

Write-Host ""
Write-Host "Done. Local commit restored (remote pull was NOT used)." -ForegroundColor Green
Write-Host "Run restart-server.bat to start the server."
