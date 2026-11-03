[CmdletBinding()]
param(
    [ValidateSet("A", "B", "Monitor", "All")]
    [string]$Target = "All",
    [switch]$Deploy,
    [switch]$InteractiveSudo
)

$ErrorActionPreference = "Stop"
$ProjectPath = "/home/labuser/woodfish-game"
$Servers = [ordered]@{
    A = @{ Host = "woodfish-a"; Service = "woodfish"; Health = "http://127.0.0.1:8000/health"; Config = "http://127.0.0.1:8000/api/config" }
    B = @{ Host = "woodfish-b"; Service = "woodfish"; Health = "http://127.0.0.1:8000/health"; Config = "http://127.0.0.1:8000/api/config" }
    Monitor = @{ Host = "woodfish-monitor"; Service = "woodfish-admin"; Health = "http://127.0.0.1:8010/health"; Config = $null }
}

function Get-Targets {
    if ($Target -eq "All") { return @("A", "B", "Monitor") }
    return @($Target)
}

function Invoke-SSH {
    param([string]$HostName, [string]$Command, [switch]$Tty)
    $arguments = @("-o", "ConnectTimeout=8")
    if (-not $InteractiveSudo) { $arguments += @("-o", "BatchMode=yes") }
    if ($Tty) { $arguments += "-tt" }
    $arguments += @($HostName, $Command)
    $output = & ssh.exe @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = $output -join [Environment]::NewLine
        throw "${HostName}: remote command failed: $details"
    }
    return ($output -join [Environment]::NewLine).Trim()
}

function Assert-LocalGit {
    $localStatus = @(git status --porcelain)
    if ($localStatus.Count -gt 0) { throw "Local Git worktree is dirty" }
    if ((git branch --show-current) -ne "main") { throw "Local branch is not main" }
    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw "Unable to fetch origin/main" }
    $script:ExpectedCommit = (git rev-parse HEAD).Trim()
    $remoteCommit = (git rev-parse origin/main).Trim()
    if ($ExpectedCommit -ne $remoteCommit) {
        throw "Local HEAD is not pushed to origin/main: $ExpectedCommit != $remoteCommit"
    }
}

function Assert-RemotePreconditions {
    param([string]$Name)
    $server = $Servers[$Name]
    $status = Invoke-SSH $server.Host "cd $ProjectPath; git status --porcelain"
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "$Name remote Git worktree is dirty: $status"
    }
    $remoteMain = Invoke-SSH $server.Host "cd $ProjectPath; git fetch --quiet origin main; git rev-parse origin/main"
    if ($remoteMain.Trim() -ne $script:ExpectedCommit) {
        throw "$Name cannot see expected origin/main commit: $remoteMain"
    }
}

function Deploy-One {
    param([string]$Name)
    $server = $Servers[$Name]
    Write-Host "`n[$Name] $($server.Host)" -ForegroundColor Cyan
    Assert-RemotePreconditions $Name
    Invoke-SSH $server.Host "cd $ProjectPath; git pull --quiet --ff-only origin main"
    Invoke-SSH $server.Host "$ProjectPath/.venv/bin/pip install -r $ProjectPath/requirements.txt"
    if ($InteractiveSudo) {
        Invoke-SSH $server.Host "sudo systemctl restart $($server.Service)" -Tty
    } else {
        Invoke-SSH $server.Host "sudo -n systemctl restart $($server.Service)"
    }
    $commit = Invoke-SSH $server.Host "cd $ProjectPath; git rev-parse --short HEAD"
    $service = Invoke-SSH $server.Host "systemctl is-active $($server.Service)"
    $health = Invoke-SSH $server.Host "curl --fail --silent --show-error --max-time 8 $($server.Health)"
    if ($service -ne "active") { throw "$Name service is not active" }
    if ($commit -ne (git rev-parse --short $script:ExpectedCommit)) { throw "$Name commit verification failed" }
    if ($server.Config) {
        $config = Invoke-SSH $server.Host "curl --fail --silent --show-error --max-time 8 $($server.Config)"
        $expectedTeam = if ($Name -eq "A") { "A" } else { "B" }
        if (($config | ConvertFrom-Json).team_id -ne $expectedTeam) { throw "$Name TEAM_ID verification failed" }
    }
    Write-Host "commit: $commit"
    Write-Host "service: $service"
    Write-Host "health: $health"
    Write-Host "result: PASS" -ForegroundColor Green
}

Assert-LocalGit
$targets = Get-Targets
Write-Host "Expected deployment commit: $($script:ExpectedCommit)"
if (-not $Deploy) {
    Write-Host "CHECK ONLY: no remote changes. Use -Deploy to update servers." -ForegroundColor Yellow
    & "$PSScriptRoot\check-servers.ps1" -Target $Target
    exit $LASTEXITCODE
}

foreach ($Name in @("A", "B", "Monitor")) {
    if ($targets -contains $Name) {
        try {
            Deploy-One $Name
        } catch {
            Write-Error "Deployment failed for ${Name}: $($_.Exception.Message)"
            exit 1
        }
    }
}
