$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args,
        [switch]$Quiet
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($Quiet) {
        & git @Args 2>&1 | Out-Null
    } else {
        $out = & git @Args 2>&1
        foreach ($line in $out) {
            $text = if ($line -is [System.Management.Automation.ErrorRecord]) { $line.ToString() } else { "$line" }
            if ([string]::IsNullOrWhiteSpace($text)) { continue }
            if ($text -match '^warning: in the working copy') { continue }
            Write-Host $text
        }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) {
        throw "git $($Args -join ' ') failed (exit $code)"
    }
}

function Test-GitRef {
    param([string]$Ref)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git show-ref --verify --quiet $Ref 2>&1 | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

function Get-GitConfigValue {
    param([string]$Key)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $val = git config $Key 2>$null
    if (-not $val) { $val = git config --global $Key 2>$null }
    $ErrorActionPreference = $prev
    return $val
}

function Ensure-GitIdentity {
    $name = Get-GitConfigValue -Key "user.name"
    $email = Get-GitConfigValue -Key "user.email"
    if ($name -and $email) { return }

    Write-Host ""
    Write-Host "Git author is required for commit." -ForegroundColor Yellow
    Write-Host "Saved in this repo only (not --global). Use GitHub email if unsure."
    Write-Host ""

    if (-not $name) {
        do { $name = Read-Host "Your name" } while ([string]::IsNullOrWhiteSpace($name))
        Invoke-Git -Args @("config", "user.name", $name.Trim())
    }
    if (-not $email) {
        do { $email = Read-Host "Your email" } while ([string]::IsNullOrWhiteSpace($email))
        Invoke-Git -Args @("config", "user.email", $email.Trim())
    }
    Write-Host ""
}

$RemoteUrl = "https://github.com/rosua4652-commits/OKX_Trading.git"
$Branch = "cursor/okx-auto-trader-2696"

Write-Host "=== OKX Auto Trader - Git Push ===" -ForegroundColor Cyan
Write-Host "Remote: $RemoteUrl"
Write-Host "Branch: $Branch"
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git is not installed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (Test-Path ".env") {
    Write-Host "Note: .env is gitignored."
    Write-Host ""
}

try {
    if (-not (Test-Path ".git")) {
        Write-Host "Initializing git repository ..."
        Invoke-Git -Args @("init")
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        git remote add origin $RemoteUrl 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Invoke-Git -Args @("remote", "set-url", "origin", $RemoteUrl)
        }
        $ErrorActionPreference = $prev
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $origin = git remote get-url origin 2>$null
    $ErrorActionPreference = $prev
    if (-not $origin) {
        Invoke-Git -Args @("remote", "add", "origin", $RemoteUrl)
    } else {
        Invoke-Git -Args @("remote", "set-url", "origin", $RemoteUrl)
    }

    if (Test-GitRef -Ref "refs/heads/$Branch") {
        Invoke-Git -Args @("checkout", $Branch)
    } elseif (Test-GitRef -Ref "refs/remotes/origin/$Branch") {
        Invoke-Git -Args @("checkout", "-b", $Branch, "origin/$Branch")
    } else {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        git checkout -b $Branch 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) {
            Invoke-Git -Args @("checkout", $Branch)
        }
        $ErrorActionPreference = $prev
    }

    Ensure-GitIdentity

    Invoke-Git -Args @("status", "-sb")

    $msg = Read-Host "Commit message [Enter=default]"
    if ([string]::IsNullOrWhiteSpace($msg)) {
        $msg = "Update OKX Auto Trader $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }

    Invoke-Git -Args @("add", "-A")
    Invoke-Git -Args @("status", "--short")
    Write-Host ""

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    git diff --cached --quiet 2>&1 | Out-Null
    $hasChanges = ($LASTEXITCODE -ne 0)
    $ErrorActionPreference = $prev

    if ($hasChanges) {
        Invoke-Git -Args @("commit", "-m", $msg)
    } else {
        Write-Host "No changes to commit."
        $force = Read-Host "Push anyway? y/N"
        if ($force -notmatch "^[yY]$") { exit 0 }
    }

    Write-Host ""
    Write-Host "Fetching remote ..."
    Invoke-Git -Args @("fetch", "origin", $Branch)

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    git rev-parse --verify "origin/$Branch" 2>&1 | Out-Null
    $hasRemote = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev

    if ($hasRemote) {
        $stashNeeded = $false
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        git diff --quiet 2>&1 | Out-Null
        $dirty = ($LASTEXITCODE -ne 0)
        git diff --cached --quiet 2>&1 | Out-Null
        $staged = ($LASTEXITCODE -ne 0)
        $ErrorActionPreference = $prev
        if ($dirty -or $staged) {
            Write-Host "Stashing local changes before rebase ..."
            Invoke-Git -Args @("stash", "push", "-m", "oat-push-$(Get-Date -Format 'yyyyMMdd-HHmmss')")
            $stashNeeded = $true
        }

        Write-Host "Rebasing onto origin/$Branch ..."
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        git pull --rebase origin $Branch 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) {
            $ErrorActionPreference = $prev
            if ($stashNeeded) { git stash pop 2>&1 | Out-Null }
            throw "git pull --rebase failed — run git-pull-sync.bat or fix conflicts, then push again"
        }
        $ErrorActionPreference = $prev

        if ($stashNeeded) {
            Write-Host "Restoring stashed changes ..."
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            git stash pop 2>&1 | ForEach-Object { Write-Host $_ }
            $ErrorActionPreference = $prev
        }
    }

    Write-Host ""
    Write-Host "Pushing to GitHub ..."
    Invoke-Git -Args @("push", "-u", "origin", $Branch)

    Write-Host ""
    Write-Host "Done: https://github.com/rosua4652-commits/OKX_Trading/tree/$Branch" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ("$($_.Exception.Message)" -match "push") {
        Write-Host "Check GitHub login and write access to the repository."
    } elseif ("$($_.Exception.Message)" -match "commit") {
        Write-Host "Set author: git config user.name / user.email (or run this script again)."
    }
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"
