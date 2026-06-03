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

function Invoke-GitSoft {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $out = & git @Args 2>&1
    foreach ($line in $out) {
        $text = if ($line -is [System.Management.Automation.ErrorRecord]) { $line.ToString() } else { "$line" }
        if (-not [string]::IsNullOrWhiteSpace($text)) { Write-Host $text }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
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

function Test-GitAncestor {
    param([string]$Ancestor, [string]$Descendant)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git merge-base --is-ancestor $Ancestor $Descendant 2>&1 | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

function Stop-InterruptedRebase {
    $rebaseDir = Join-Path $Root ".git\rebase-merge"
    $rebaseApply = Join-Path $Root ".git\rebase-apply"
    if (-not ((Test-Path $rebaseDir) -or (Test-Path $rebaseApply))) { return }

    Write-Host "Interrupted rebase detected - aborting to keep your local files." -ForegroundColor Yellow
    Invoke-GitSoft -Args @("rebase", "--abort") | Out-Null
    if (Test-GitRef -Ref "refs/heads/$script:Branch") {
        Invoke-Git -Args @("checkout", $script:Branch)
    }
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

function Push-ToOrigin {
    param([string]$BranchName)

    Write-Host ""
    Write-Host "Pushing to GitHub (no pull --rebase; local files stay as-is) ..."
    $code = Invoke-GitSoft -Args @("push", "-u", "origin", $BranchName)
    if ($code -eq 0) { return }

    Write-Host ""
    Write-Host "Normal push was rejected (remote history differs from local)." -ForegroundColor Yellow
    Write-Host "GitHub still has an older snapshot; your PC has the full project."
    Write-Host "To update GitHub WITHOUT rolling back this folder, use force-with-lease."
    Write-Host ""
    $ans = Read-Host "Force push with lease? y/N"
    if ($ans -notmatch "^[yY]$") {
        throw "Push cancelled. Run restore-local.bat if files look old after a failed rebase."
    }
    Invoke-Git -Args @("push", "--force-with-lease", "-u", "origin", $BranchName)
}

$RemoteUrl = "https://github.com/rosua4652-commits/OKX_Trading.git"
$Branch = "cursor/okx-auto-trader-2696"

Write-Host "=== OKX Auto Trader - Git Push ===" -ForegroundColor Cyan
Write-Host "Remote: $RemoteUrl"
Write-Host "Branch: $Branch"
Write-Host "Note: pull --rebase is NOT used (it caused old-version rollback)."
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git is not installed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (Test-Path ".env") {
    Write-Host ".env is gitignored."
    Write-Host ""
}

try {
    Stop-InterruptedRebase

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
        Write-Host "Local branch missing - creating from your latest local commits, not old remote only."
        Invoke-Git -Args @("checkout", "-b", $Branch)
    } else {
        Invoke-Git -Args @("checkout", "-b", $Branch)
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
    Write-Host "Fetching remote (compare only) ..."
    Invoke-Git -Args @("fetch", "origin", $Branch)

    $localHead = (git rev-parse HEAD).Trim()
    $hasRemote = Test-GitRef -Ref "refs/remotes/origin/$Branch"

    if ($hasRemote) {
        $remoteHead = (git rev-parse "origin/$Branch").Trim()
        Write-Host "Local:  $localHead"
        Write-Host "Remote: $remoteHead"

        if (Test-GitAncestor -Ancestor $remoteHead -Descendant $localHead) {
            $ahead = (git rev-list --count "$remoteHead..$localHead").Trim()
            Write-Host "Local is $ahead commit(s) ahead of GitHub - push only." -ForegroundColor Green
        } elseif (Test-GitAncestor -Ancestor $localHead -Descendant $remoteHead) {
            Write-Host ""
            Write-Host "[WARN] GitHub is ahead of your PC. pull --rebase is disabled here." -ForegroundColor Yellow
            Write-Host "Use restore-local.bat to keep this folder. Do not use git-pull-sync.bat."
            $merge = Read-Host "Try merge origin/$Branch into local? y/N"
            if ($merge -match "^[yY]$") {
                Invoke-Git -Args @("merge", "origin/$Branch", "-m", "merge origin/$Branch")
            } else {
                throw "Push aborted - update local copy manually if you really need remote changes."
            }
        } else {
            Write-Host ""
            Write-Host "Histories differ (common after first local init). Will push; force-with-lease may be needed." -ForegroundColor Yellow
        }
    }

    Push-ToOrigin -BranchName $Branch

    Write-Host ""
    Write-Host "Done: https://github.com/rosua4652-commits/OKX_Trading/tree/$Branch" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "If the project folder looks old: run restore-local.bat" -ForegroundColor Yellow
    if ("$($_.Exception.Message)" -match "push") {
        Write-Host "Check GitHub login and write access to the repository."
    }
    Read-Host "Press Enter to exit"
    exit 1
}

Read-Host "Press Enter to exit"
