# watchdog.ps1 -- Auto-restart daemons that crash
# Polls every 60 seconds, restarts any daemon whose PID file is missing or stale.
# Run as a background process via larry-start.ps1 or Task Scheduler.
#
# Never restarted:
#   - a daemon with a <name>.disabled flag in .notifications/
#   - a part switched off in the control room (data/web/parts-off.json, {"off": ["wispr"]})
#   - a part resting in game mode (data/web/game-mode.json, {"on": true, "parts": [{"id": "milla"}]})
# Without the last two, the watchdog restarts within a minute what the owner just turned off.
# A game mode that was ended a moment ago still counts as resting for a short window
# ($GAME_MODE_ENDING_S): the start script is bringing the parts back right then, and a
# second instance started by the watchdog would collide on the same singleton.
#
# Also, every pass:
#   - the web app and its tunnel are kept up (they are the way in from a phone, also
#     during game mode): restarted through stack-start.ps1 -Only Web
#   - every ~hour, orphaned MCP servers left behind by dead Claude Code sessions are
#     cleaned up
#
# Configure $VaultPath and the $daemons registry below.

param(
    [string]$VaultPath = $env:VAULT_ROOT
)

if (-not $VaultPath) {
    Write-Error "VAULT_ROOT not set and -VaultPath not provided"
    exit 1
}

$ErrorActionPreference = "Continue"
$NotifDir = Join-Path $VaultPath ".notifications"
$LogFile  = Join-Path $NotifDir "watchdog.log"

if (-not (Test-Path $NotifDir)) {
    New-Item -Path $NotifDir -ItemType Directory -Force | Out-Null
}

$env:PYTHONIOENCODING = "utf-8"
. (Join-Path $PSScriptRoot "proc-names.ps1")

# === Daemon registry ===
# Customize: add your own daemons here.
# Each entry needs Name, PidFile, LockFile (optional), Script, WorkDir, and Args (optional).
$daemons = @(
    @{
        Name     = "Parry"
        PidFile  = "parry-guardian.pid"
        LockFile = "parry-guardian.lock"
        Script   = Join-Path $VaultPath "bus\parry_service.py"
        WorkDir  = Join-Path $VaultPath "bus"
    }
    @{
        Name     = "Tarry"
        PidFile  = "tarry.pid"
        LockFile = "tarry.lock"
        Script   = Join-Path $VaultPath "agents\tarry_service.py"
        WorkDir  = Join-Path $VaultPath "agents"
    }
    @{
        Name     = "Carry"
        PidFile  = "carry.pid"
        LockFile = "carry.lock"
        Script   = Join-Path $VaultPath "agents\carry_service.py"
        WorkDir  = Join-Path $VaultPath "agents"
    }
    @{
        Name     = "Bot-listener"
        PidFile  = "bot-listener.pid"
        LockFile = "bot-listener.lock"
        Script   = Join-Path $VaultPath "notifications\bot_listener.py"
        WorkDir  = Join-Path $VaultPath "notifications"
    }
    @{
        Name     = "Event-dispatcher"
        PidFile  = "event-dispatcher.pid"
        LockFile = "event-dispatcher.lock"
        Script   = Join-Path $VaultPath "agents\event_dispatcher.py"
        WorkDir  = Join-Path $VaultPath "agents"
    }
    # One task watcher per agent, same script. Keep this list in step with the
    # start script: a watcher missing here was down for weeks before anyone noticed.
    @{
        Name     = "Task-watcher-larry"
        PidFile  = "task-watcher-larry.pid"
        LockFile = "task-watcher-larry.lock"
        Script   = Join-Path $VaultPath "agents\agent_task_watcher.py"
        Args     = "--agent larry"
        WorkDir  = Join-Path $VaultPath "agents"
    }
    @{
        Name     = "Task-watcher-barry"
        PidFile  = "task-watcher-barry.pid"
        LockFile = "task-watcher-barry.lock"
        Script   = Join-Path $VaultPath "agents\agent_task_watcher.py"
        Args     = "--agent barry"
        WorkDir  = Join-Path $VaultPath "agents"
    }
)

# Parts the owner switched off or that rest in game mode. Ids are the daemon name in lowercase.
$WebDataDir = Join-Path $VaultPath "data\web"
$GAME_MODE_ENDING_S = 180
function Get-RestingParts {
    $out = @()
    $off = Join-Path $WebDataDir "parts-off.json"
    if (Test-Path $off) {
        try { $out += @((Get-Content $off -Raw -Encoding UTF8 | ConvertFrom-Json).off | ForEach-Object { "$_".ToLower() }) } catch { }
    }
    $gm = Join-Path $WebDataDir "game-mode.json"
    if (Test-Path $gm) {
        try {
            $g = Get-Content $gm -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($g.on -eq $true) {
                $out += @($g.parts | ForEach-Object { "$($_.id)".ToLower() })
            } elseif ($g.ended_at) {
                # Ended a moment ago: the start script is bringing the parts back now
                try {
                    $sinceEnd = ([DateTimeOffset]::Now - [DateTimeOffset]::Parse("$($g.ended_at)")).TotalSeconds
                    if ($sinceEnd -ge -5 -and $sinceEnd -le $GAME_MODE_ENDING_S) {
                        $out += @($g.parts | ForEach-Object { "$($_.id)".ToLower() })
                    }
                } catch { }
            }
        } catch { }
    }
    return $out
}

# Cloud credentials guard: everything that goes through a cloud SDK dies quietly
# when the credentials file disappears (an OS reinstall is enough). File check
# only, no network call. Logged once per change, not every minute.
function Test-CloudCredentials {
    if ($env:GOOGLE_APPLICATION_CREDENTIALS) { return (Test-Path $env:GOOGLE_APPLICATION_CREDENTIALS) }
    return (Test-Path (Join-Path $env:APPDATA "gcloud\application_default_credentials.json"))
}

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts [watchdog] $Msg"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Test-DaemonAlive {
    param([string]$PidFile)
    $pidPath = Join-Path $NotifDir $PidFile
    if (-not (Test-Path $pidPath)) { return $false }
    $dpid = (Get-Content $pidPath -Raw).Trim()
    try {
        $proc = Get-Process -Id $dpid -ErrorAction Stop
        if ($proc.ProcessName -match $StackPyProcRx) { return $true }
    } catch { }
    return $false
}

function Clear-StaleFiles {
    param([string]$PidFile, [string]$LockFile)
    $pidPath = Join-Path $NotifDir $PidFile
    if (Test-Path $pidPath) { Remove-Item $pidPath -Force -ErrorAction SilentlyContinue }
    if ($LockFile) {
        $lockPath = Join-Path $NotifDir $LockFile
        if (Test-Path $lockPath) { Remove-Item $lockPath -Force -ErrorAction SilentlyContinue }
    }
}

function Restart-Daemon {
    param([hashtable]$Daemon)
    Clear-StaleFiles -PidFile $Daemon.PidFile -LockFile $Daemon.LockFile
    $dname = $Daemon.Name.ToLower()
    $errFile = Join-Path $NotifDir "$dname.log.err"
    $argList = @($Daemon.Script)
    if ($Daemon.Args) { $argList += ($Daemon.Args -split ' ') }
    # Named exe (ml-<name>.exe) when the deploy made one, pythonw otherwise
    $proc = Start-Process -FilePath (Get-StackPythonExe $Daemon.Name "pythonw") -ArgumentList $argList -WorkingDirectory $Daemon.WorkDir -WindowStyle Hidden -PassThru -RedirectStandardError $errFile
    Start-Sleep -Milliseconds 800
    if ($proc.HasExited) {
        return $false
    }
    return $true
}

# === The web app and its tunnel stay up ===
# They are the way in from a phone, also in game mode, and neither is in $daemons:
# the web app needs the access gate to get its tunnel port. So the restart goes the
# same way as the logon task: stack-start.ps1 -Only Web, which starts the tunnel
# client too if it is down.
# Down two passes in a row before anything is done: a restart from the web UI has
# it down for a moment on purpose and starts it itself. After that at most one try
# per $WEB_RETRY_S, the gate can take a minute on a flaky network.
$WebPort = 8801
$WEB_RETRY_S = 300
$webDownLoops = 0
$webLastTry = [DateTime]::MinValue
function Get-PortListenerPid([int]$Port) { return Get-StackPortListenerPid -Port $Port }
function Test-WebAndTunnelUp {
    if (-not (Get-PortListenerPid $WebPort)) { return $false }
    # Without a tunnel client installed there is nothing to keep up
    $cf = $env:CLOUDFLARED_EXE
    if (-not $cf) { $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
    if (-not $cf) { return $true }
    return [bool](Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue)
}
function Start-WebAndTunnel {
    $startScript = Join-Path $PSScriptRoot "stack-start.ps1"
    $webLog = Join-Path $NotifDir "web-autostart.log"
    $cmd = "& '$startScript' -Only Web *>> '$webLog'"
    Start-Process powershell.exe -WindowStyle Hidden `
        -ArgumentList "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "`"$cmd`""
}

# === Orphaned MCP servers ===
# A session's MCP servers are started by claude.exe, one set per Claude Code session.
# When the session dies without cleaning up they are left without a parent and look
# like duplicates. Never touches a process with a live claude.exe ancestor, never the
# memory daemon (it is not a session child), never anything younger than two minutes.
# The pattern matches script or module names containing mcp_server; add your own.
$McpPattern = 'mcp_server'
$MemoryPort = 18923
function Stop-OrphanSessionMcp {
    $snap = @{}
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object { $snap[[int]$_.ProcessId] = $_ }
    $primary = Get-PortListenerPid $MemoryPort
    foreach ($p in @($snap.Values)) {
        if ($p.Name -notmatch $StackPyNameRx -or -not $p.CommandLine) { continue }
        if ($p.CommandLine -notmatch $McpPattern) { continue }
        if ($primary -and [int]$p.ProcessId -eq [int]$primary) { continue }
        if ($p.CreationDate -gt (Get-Date).AddMinutes(-2)) { continue }
        $owned = $false
        $cur = $p
        for ($i = 0; $i -lt 4 -and $cur; $i++) {
            $parent = $snap[[int]$cur.ParentProcessId]
            if (-not $parent -or $parent.CreationDate -gt $cur.CreationDate) { break }
            if ($parent.Name -eq "claude.exe") { $owned = $true; break }
            $cur = $parent
        }
        if ($owned) { continue }
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Log "MCP orphan killed: pid=$($p.ProcessId) ($($p.Name))"
        } catch { }
    }
}
$MCP_CHECK_EVERY = 60   # every 60th pass, about once an hour
$mcpLoops = 0

# PID file for watchdog itself
$watchdogPid = Join-Path $NotifDir "watchdog.pid"
"$PID" | Out-File -FilePath $watchdogPid -Encoding ascii -NoNewline

Write-Log "started (pid=$PID), poll=60s"
$credsOk = $null

while ($true) {
    $mcpLoops++
    if ($mcpLoops -ge $MCP_CHECK_EVERY) { $mcpLoops = 0; Stop-OrphanSessionMcp }

    if (Test-WebAndTunnelUp) {
        $webDownLoops = 0
    } else {
        $webDownLoops++
        if ($webDownLoops -ge 2 -and ((Get-Date) - $webLastTry).TotalSeconds -ge $WEB_RETRY_S) {
            Write-Log "Web app or tunnel DOWN - starting (stack-start -Only Web)"
            $webLastTry = Get-Date
            Start-WebAndTunnel
        }
    }

    $now = Test-CloudCredentials
    if ($credsOk -ne $null -and $now -ne $credsOk) {
        if ($now) { Write-Log "cloud credentials back" } else { Write-Log "CLOUD CREDENTIALS MISSING -- every cloud SDK call will fail" }
    } elseif ($credsOk -eq $null -and -not $now) {
        Write-Log "CLOUD CREDENTIALS MISSING -- every cloud SDK call will fail"
    }
    $credsOk = $now

    $resting = @(Get-RestingParts)
    foreach ($d in $daemons) {
        $dkey = $d.Name.ToLower()
        if (Test-Path (Join-Path $NotifDir "$dkey.disabled")) { continue }
        if ($resting -contains $dkey) { continue }
        $alive = Test-DaemonAlive -PidFile $d.PidFile
        # Read game mode once more right before the restart: $resting is from the start
        # of the pass, and a game mode switched on mid-pass stops parts while we iterate.
        if (-not $alive -and (@(Get-RestingParts) -contains $dkey)) { continue }
        if (-not $alive) {
            $dname = $d.Name
            Write-Log "$dname DOWN - restarting"
            if ($dname -eq "Parry") {
                Start-Sleep -Milliseconds 500
            }
            $ok = Restart-Daemon -Daemon $d
            if ($ok) {
                $newPidPath = Join-Path $NotifDir $d.PidFile
                $dpid = ""
                if (Test-Path $newPidPath) { $dpid = (Get-Content $newPidPath -Raw).Trim() }
                Write-Log "$dname restarted (pid=$dpid)"
            } else {
                Write-Log "$dname FAILED to restart"
            }
        }
    }
    Start-Sleep -Seconds 60
}
