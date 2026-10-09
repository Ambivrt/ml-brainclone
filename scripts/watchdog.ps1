# watchdog.ps1 -- Auto-restart daemons that crash
# Polls every 60 seconds, restarts any daemon whose PID file is missing or stale.
# Run as a background process via larry-start.ps1 or Task Scheduler.
#
# Never restarted:
#   - a daemon with a <name>.disabled flag in .notifications/
#   - a part switched off in the control room (data/web/parts-off.json, {"off": ["wispr"]})
#   - a part resting in game mode (data/web/game-mode.json, {"on": true, "parts": [{"id": "milla"}]})
# Without the last two, the watchdog restarts within a minute what the owner just turned off.
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
            if ($g.on -eq $true) { $out += @($g.parts | ForEach-Object { "$($_.id)".ToLower() }) }
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
        if ($proc.ProcessName -match "python") { return $true }
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
    $proc = Start-Process -FilePath "pythonw" -ArgumentList $argList -WorkingDirectory $Daemon.WorkDir -WindowStyle Hidden -PassThru -RedirectStandardError $errFile
    Start-Sleep -Milliseconds 800
    if ($proc.HasExited) {
        return $false
    }
    return $true
}

# PID file for watchdog itself
$watchdogPid = Join-Path $NotifDir "watchdog.pid"
"$PID" | Out-File -FilePath $watchdogPid -Encoding ascii -NoNewline

Write-Log "started (pid=$PID), poll=60s"
$credsOk = $null

while ($true) {
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
