[CmdletBinding()]
param(
    [ValidateSet("A", "B", "Monitor", "All")]
    [string]$Target = "All"
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

function Invoke-RemoteRead {
    param([string]$HostName, [string]$Command)
    $output = & ssh.exe -o BatchMode=yes -o ConnectTimeout=8 $HostName $Command 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = $output -join [Environment]::NewLine
        throw "${HostName}: SSH or remote query failed: $details"
    }
    return ($output -join [Environment]::NewLine).Trim()
}

$failed = $false
foreach ($Name in (Get-Targets)) {
    $server = $Servers[$Name]
    Write-Host "`n[$Name] $($server.Host)" -ForegroundColor Cyan
    try {
        $commit = Invoke-RemoteRead $server.Host "cd $ProjectPath; git rev-parse --short HEAD"
        $status = Invoke-RemoteRead $server.Host "cd $ProjectPath; git status --porcelain"
        $service = Invoke-RemoteRead $server.Host "systemctl is-active $($server.Service)"
        $health = Invoke-RemoteRead $server.Host "curl --fail --silent --show-error --max-time 8 $($server.Health)"

        Write-Host "commit: $commit"
        Write-Host "worktree: $(if ([string]::IsNullOrWhiteSpace($status)) { 'clean' } else { $status })"
        Write-Host "service: $service"
        Write-Host "health: $health"
        if ($service -ne "active") { throw "$Name service is not active" }
        if (-not [string]::IsNullOrWhiteSpace($status)) { throw "$Name remote Git worktree is dirty" }
        if ($server.Config) {
            $config = Invoke-RemoteRead $server.Host "curl --fail --silent --show-error --max-time 8 $($server.Config)"
            Write-Host "config: $config"
            $expectedTeam = if ($Name -eq "A") { "A" } else { "B" }
            if (($config | ConvertFrom-Json).team_id -ne $expectedTeam) {
                throw "$Name TEAM_ID does not match expected value"
            }
        }
        Write-Host "result: PASS" -ForegroundColor Green
    } catch {
        $failed = $true
        Write-Host "result: FAIL - $($_.Exception.Message)" -ForegroundColor Red
    }
}
if ($failed) { exit 1 }
