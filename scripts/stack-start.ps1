# stack-start.ps1 -- start the daemon stack and the local web apps
#
# Checks every daemon: already running, skip. Otherwise start it.
#   .\stack-start.ps1                    full start
#   .\stack-start.ps1 -Force             stop everything first, then start
#   .\stack-start.ps1 -Only Memory       start only the named parts; flags and other parts untouched
#   .\stack-start.ps1 -Force -Only Web   stop and start only the named parts
#
# -Force -Only stops only what it names. An earlier version always ran the full
# stop under -Force, so restarting the web app took down the whole stack,
# the tunnel and every scheduled job.
#
# Parts the owner switched off in the control room (data/web/parts-off.json)
# are skipped by a full start and by -Force, even after a reboot. -Only starts
# them anyway: that is how the control room turns a part back on.
#
# A full start means "I want everything running": it clears .disabled and
# circuit-breaker flags. -Only never touches flags.
#
# Web apps start on their local port, always. The tunnel port is opened only
# when the access policy in front of the tunnel verifies (see Invoke-AccessGate).
# Without a verified policy the app stays local, never open on the internet.

param([switch]$Force, [string[]]$Only)

$VaultPath = $env:VAULT_ROOT
if (-not $VaultPath) { Write-Error "VAULT_ROOT not set"; exit 1 }
$ErrorActionPreference = "Continue"
$NotifDir = Join-Path $VaultPath ".notifications"
$WebData  = Join-Path $VaultPath "data\web"
if (-not (Test-Path $NotifDir)) { New-Item -Path $NotifDir -ItemType Directory -Force | Out-Null }
$env:PYTHONIOENCODING = "utf-8"

# === Daemon registry ===
# Order matters: the gatekeeper first, then services, then listeners.
# Console + HideConsole: the process needs real I/O handles (ONNX and Chroma hang
# without them). It runs under a hidden cmd with stdout+stderr appended to <name>.log.
$daemons = @(
    @{ Name = "Parry";  PidFile = "parry.pid";  Script = Join-Path $VaultPath "bus\parry_service.py";    WorkDir = Join-Path $VaultPath "bus" }
    @{ Name = "Memory"; PidFile = "memory.pid"; Script = Join-Path $VaultPath "memory\memory_server.py"; WorkDir = Join-Path $VaultPath "memory"; Port = 18923; Console = $true; HideConsole = $true }
    @{ Name = "Tarry";  PidFile = "tarry.pid";  Script = Join-Path $VaultPath "agents\tarry_service.py";  WorkDir = Join-Path $VaultPath "agents" }
    @{ Name = "Carry";  PidFile = "carry.pid";  Script = Join-Path $VaultPath "agents\carry_service.py";  WorkDir = Join-Path $VaultPath "agents" }
    @{ Name = "Bot-listener"; PidFile = "bot-listener.pid"; Script = Join-Path $VaultPath "notifications\bot_listener.py"; WorkDir = Join-Path $VaultPath "notifications" }
    # One task watcher per agent, same script. Keep in step with watchdog.ps1.
    @{ Name = "Task-watcher-larry"; PidFile = "task-watcher-larry.pid"; Script = Join-Path $VaultPath "agents\agent_task_watcher.py"; Args = "--agent larry"; WorkDir = Join-Path $VaultPath "agents" }
    @{ Name = "Task-watcher-barry"; PidFile = "task-watcher-barry.pid"; Script = Join-Path $VaultPath "agents\agent_task_watcher.py"; Args = "--agent barry"; WorkDir = Join-Path $VaultPath "agents" }
)

# === App registry (port based) ===
# Port = local listener on 127.0.0.1, always on. TunnelPort = listener behind the
# tunnel, opened only with a verified access policy. CmdMatch: something already
# listening on one of the ports is adopted only if it is python with CmdMatch in
# its command line. Anything else means the port is taken.
$apps = @(
    @{ Name = "Web"; Port = 8801; TunnelPort = 8800; Script = Join-Path $VaultPath "apps\web\app.py"; WorkDir = Join-Path $VaultPath "apps\web"; PidFile = "web.pid"; CmdMatch = "apps\web" }
)
$AccessScript = Join-Path $VaultPath "operations\access_policy.py"

# === Access gate for apps behind the tunnel ===
# Exit code of `access_policy.py verify`: 0 verified, 2 policy wrong, 3 not set up
# (no token yet: the app runs local and that is not an error), 4 API error.
# Exit 4 is a flaky network, so it is retried: a restart from the phone ends here,
# and one failed call would otherwise start the app without its tunnel and lock
# the phone out. 2 and 3 are answers, not network errors: no retry.
function Invoke-AccessGate {
    param([string]$Script, [int]$Attempts = 6, [int]$WaitSeconds = 10)
    if (-not (Test-Path -LiteralPath $Script)) { return 99 }
    $code = 99
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $global:LASTEXITCODE = 99
        try { & python -X utf8 $Script verify | Out-Null } catch { $global:LASTEXITCODE = 0; return 98 }
        $code = [int]$global:LASTEXITCODE
        $global:LASTEXITCODE = 0     # the gate's code is the return value, not this script's exit code
        if ($code -ne 4 -or $attempt -ge $Attempts) { break }
        Write-Host "  [~] access policy did not answer (exit 4), retry in $WaitSeconds s ($($attempt + 1) of $Attempts)"
        Start-Sleep -Seconds $WaitSeconds
    }
    return $code
}

function Get-PortListenerPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess } else { return $null }
}

function Test-AppProcess([int]$ProcessId, [string]$Match) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        return ($p.Name -match "^python" -and $p.CommandLine -like "*$Match*")
    } catch { return $false }
}

function Test-DaemonAlive([hashtable]$Daemon) {
    if ($Daemon.Port) { return [bool](Get-PortListenerPid $Daemon.Port) }
    $pidPath = Join-Path $NotifDir $Daemon.PidFile
    if (-not (Test-Path $pidPath)) { return $false }
    $dpid = (Get-Content $pidPath -Raw).Trim()
    try { return ((Get-Process -Id $dpid -ErrorAction Stop).ProcessName -match "python") } catch { return $false }
}

function Start-Daemon([hashtable]$Daemon) {
    $name = $Daemon.Name.ToLower()
    $scriptArgs = $Daemon.Script
    if ($Daemon.Args) { $scriptArgs = "$scriptArgs $($Daemon.Args)" }
    if ($Daemon.Console -and $Daemon.HideConsole) {
        # Append, never overwrite: a restart must not erase the evidence of why it hung.
        # Rotated at 5 MB, one generation.
        $out = Join-Path $NotifDir "$name.log"
        if ((Test-Path $out) -and ((Get-Item $out).Length -gt 5MB)) { Move-Item -Force $out "$out.1" }
        Start-Process cmd -ArgumentList "/c cd /d `"$($Daemon.WorkDir)`" && python -u $scriptArgs >> `"$out`" 2>&1" -WindowStyle Hidden | Out-Null
    } else {
        Start-Process -FilePath "pythonw" -ArgumentList $scriptArgs -WorkingDirectory $Daemon.WorkDir -WindowStyle Hidden `
            -RedirectStandardError (Join-Path $NotifDir "$name.log.err") | Out-Null
    }
    if ($Daemon.Port) {
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $deadline) { if (Get-PortListenerPid $Daemon.Port) { return $true }; Start-Sleep -Milliseconds 500 }
        return $false
    }
    Start-Sleep -Milliseconds 800
    return (Test-DaemonAlive $Daemon)
}

# === Main ===
if ($Only) {
    $daemons = @($daemons | Where-Object { $Only -contains $_.Name })
    $apps    = @($apps    | Where-Object { $Only -contains $_.Name })
    if ($daemons.Count -eq 0 -and $apps.Count -eq 0) { Write-Host "  [!] -Only matched nothing: $($Only -join ', ')"; exit 1 }
}

if ($Force -and $Only) {
    Write-Host "--- Force: stopping only $($Only -join ', ') ---"
    foreach ($a in $apps) {
        foreach ($p in @($a.Port, $a.TunnelPort)) {
            if (-not $p) { continue }
            $lp = Get-PortListenerPid $p
            if ($lp -and (Test-AppProcess $lp $a.CmdMatch)) { Stop-Process -Id $lp -Force -ErrorAction SilentlyContinue; Write-Host "  [x] $($a.Name) stopped (port $p)" }
        }
    }
    foreach ($d in $daemons) {
        $pidPath = Join-Path $NotifDir $d.PidFile
        if (Test-Path $pidPath) { Stop-Process -Id ((Get-Content $pidPath -Raw).Trim()) -Force -ErrorAction SilentlyContinue; Write-Host "  [x] $($d.Name) stopped" }
    }
    Start-Sleep -Seconds 1
} elseif ($Force) {
    Write-Host "--- Force: stopping everything first ---"
    & (Join-Path $PSScriptRoot "stack-stop.ps1")
}

if (-not $Only) {
    $off = @()
    $offFile = Join-Path $WebData "parts-off.json"
    if (Test-Path $offFile) { try { $off = @((Get-Content $offFile -Raw -Encoding UTF8 | ConvertFrom-Json).off | ForEach-Object { "$_".ToLower() }) } catch { } }
    if ($off.Count) {
        Write-Host "  [-] switched off in the control room: $($off -join ', ')"
        $daemons = @($daemons | Where-Object { $off -notcontains $_.Name.ToLower() })
        $apps    = @($apps    | Where-Object { $off -notcontains $_.Name.ToLower() })
    }
    Get-ChildItem $NotifDir -Filter "*.disabled" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem $NotifDir -Filter "*.circuit-broken" -ErrorAction SilentlyContinue | Remove-Item -Force
}

$started = 0; $up = 0; $failed = 0
Write-Host "--- Daemons ---"
foreach ($d in $daemons) {
    if (Test-DaemonAlive $d) { Write-Host "  [=] $($d.Name) already up"; $up++; continue }
    if (Start-Daemon $d) { Write-Host "  [+] $($d.Name) started"; $started++ } else { Write-Host "  [!] $($d.Name) FAILED"; $failed++ }
}

Write-Host "--- Apps ---"
foreach ($a in $apps) {
    $taken = $false
    foreach ($p in @($a.Port, $a.TunnelPort)) {
        $lp = if ($p) { Get-PortListenerPid $p } else { $null }
        if ($lp -and -not (Test-AppProcess $lp $a.CmdMatch)) { Write-Host "  [!] $($a.Name): port $p is taken by another process"; $taken = $true }
    }
    if ($taken) { $failed++; continue }
    if (Get-PortListenerPid $a.Port) { Write-Host "  [=] $($a.Name) already up"; $up++; continue }
    $appArgs = $a.Script
    if ($a.TunnelPort) {
        $gate = Invoke-AccessGate $AccessScript
        if ($gate -eq 0) { $appArgs = "$appArgs --tunnel" }
        elseif ($gate -eq 3) { Write-Host "  [-] $($a.Name): tunnel not set up yet, local only" }
        else { Write-Host "  [!] $($a.Name): access policy did not verify (exit $gate), local only"; $failed++ }
    }
    Start-Process -FilePath "pythonw" -ArgumentList $appArgs -WorkingDirectory $a.WorkDir -WindowStyle Hidden | Out-Null
    $deadline = (Get-Date).AddSeconds(15); $ok = $false
    while ((Get-Date) -lt $deadline) { $lp = Get-PortListenerPid $a.Port; if ($lp) { "$lp" | Out-File (Join-Path $NotifDir $a.PidFile) -Encoding ascii -NoNewline; $ok = $true; break }; Start-Sleep -Milliseconds 500 }
    if ($ok) { Write-Host "  [+] $($a.Name) started (port $($a.Port))"; $started++ } else { Write-Host "  [!] $($a.Name) FAILED"; $failed++ }
}

Write-Host ""
Write-Host "Started: $started | Already up: $up | Failed: $failed"
if ($failed) { exit 2 }
