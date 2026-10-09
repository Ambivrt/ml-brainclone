# larry-startup.ps1 -- open one Windows Terminal window per brain session
#
# - Each agent gets its own window with its own profile and colour
# - Positions come from window-positions.json (run larry-save-positions.ps1 first)
# - An agent whose window is already open is skipped (one instance per agent)
#
# This opens the interactive sessions only. The daemon stack is stack-start.ps1.
# Model and effort live in the vault's .claude/settings.json, not in the terminal
# profile: a --model or --effort flag in a profile silently overrides settings.json.
# A profile passes --remote-control <name> so each session is reachable from the phone.

param(
    [int]$DelaySeconds = 5
)

Start-Sleep -Seconds $DelaySeconds

function Test-AgentRunning([string]$agentName) {
    foreach ($p in (Get-Process WindowsTerminal -ErrorAction SilentlyContinue)) {
        if ($p.MainWindowTitle -like "*$agentName*") { return $true }
    }
    return $false
}

$posFile = "$PSScriptRoot\window-positions.json"
$positions = $null
if (Test-Path $posFile) {
    $positions = Get-Content $posFile -Encoding UTF8 | ConvertFrom-Json
} else {
    Write-Host "[WARN] window-positions.json missing, opening without positions." -ForegroundColor Yellow
    Write-Host "       Run scripts\larry-save-positions.ps1 after placing the windows." -ForegroundColor Yellow
}

$agents = @(
    @{ Name = "Larry"; Profile = "Larry" },
    @{ Name = "Barry"; Profile = "Barry" },
    @{ Name = "Harry"; Profile = "Harry" },
    @{ Name = "Garry"; Profile = "Garry" }
)

foreach ($agent in $agents) {
    $name = $agent.Name
    if (Test-AgentRunning $name) {
        Write-Host "[--] $name already running, skipping"
        continue
    }
    $posArg = ""
    if ($positions -and $positions.$name) {
        $posArg = "--pos $($positions.$name.X),$($positions.$name.Y) "
    }
    # -w new forces a separate window (not a new tab in an existing one).
    # --title names the window so Test-AgentRunning can find it.
    $wtArgs = "$($posArg)-w new new-tab --profile `"$($agent.Profile)`" --title `"$name`""
    Start-Process "wt.exe" -ArgumentList $wtArgs
    Write-Host "[OK] $name started"
    # Give Windows Terminal time to register the window before the next one
    Start-Sleep -Milliseconds 600
}

Write-Host ""
Write-Host "Sessions are open."
