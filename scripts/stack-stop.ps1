# stack-stop.ps1 -- stop everything stack-start.ps1 starts. Idempotent.
#
#   .\stack-stop.ps1         stop the stack, leave the web app and its tunnel up
#   .\stack-stop.ps1 -All    stop those too (stack-start -Force does this so the
#                            web app picks up new code)
#
# The web app is the way in from a phone, also while the rest is off and during
# game mode, so a normal stop leaves it and the tunnel running.
#
# Order:
#   0. The watchdog first, or it restarts everything else within 60 s.
#   1. The memory server gracefully: it holds an unflushed vector index, and a
#      hard kill has corrupted the index before. Hard kill only as a fallback.
#   2. Daemons by pid file, each with its whole process tree (cmd /c wrappers
#      spawn python; killing the parent alone leaves orphans).
#   3. Apps by port. The port is the truth, the pid file a fallback.
#   4. Orphan sweep: python processes running one of the stack's scripts.
#   5. The tunnel client, with -All only.
#
# This script only ever kills the stack's own processes:
#   - A pid file or a port is only a number. Before anything is killed the process
#     behind it must have the right program name (python, pythonw or a named
#     ml-<name>.exe) and the stack on its command line. Anything else is another
#     process that got the same pid, and is left alone.
#   - Windows reuses pids. A process that started AFTER the real parent died can
#     carry the parent's pid, which makes old processes look like its children.
#     winlogon and explorer always have a dead parent. A stop that walked into
#     them once took down the user session mid-stop. So: a child must be younger
#     than its parent, and protected system process names are never touched.
#   - Processes owned by a live Claude Code session are spared. A session's MCP
#     servers have claude.exe as an ancestor, and Claude Code never restarts them:
#     killed, they stay gone in every open window until /mcp or a restart.

param([switch]$All)

$VaultPath = $env:VAULT_ROOT
if (-not $VaultPath) { Write-Error "VAULT_ROOT not set"; exit 1 }
$NotifDir = Join-Path $VaultPath ".notifications"
$MemoryPort = 18923
$AppPorts = @(8801, 8800)
$AppMatch = 'apps\\web\\'     # regex: the web app's script on a command line
. (Join-Path $PSScriptRoot "proc-names.ps1")
$VaultRx = [regex]::Escape($VaultPath)

$ProtectedNames = @(
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe",
    "logonui.exe", "userinit.exe", "explorer.exe", "sihost.exe", "taskhostw.exe",
    "ctfmon.exe", "runtimebroker.exe", "windowsterminal.exe", "openconsole.exe"
)

function Stop-ProcessTree([int]$ProcId) {
    if ($ProcId -le 4 -or $ProcId -eq $PID) { return }
    $me = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
    if (-not $me) { return }
    if ($ProtectedNames -contains "$($me.Name)".ToLower()) {
        Write-Host "  [!] $($me.Name) pid=$ProcId is a system process, left alone"
        return
    }
    foreach ($c in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcId" -ErrorAction SilentlyContinue)) {
        if ($c.ProcessId -eq $PID) { continue }
        if ($c.CreationDate -lt $me.CreationDate) {
            Write-Host "  [!] $($c.Name) pid=$($c.ProcessId) is older than pid $ProcId (reused pid), left alone"
            continue
        }
        Stop-ProcessTree $c.ProcessId
    }
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
}

# Is the pid still the stack's process? Right program name, right command line.
function Test-StackProcess {
    param([string]$ProcId, [string]$NamePattern = $StackPyNameRx, [string]$Match = $VaultRx)
    if ($ProcId -notmatch '^\d+$') { return $false }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    # A broken pattern must never turn into a yes
    try {
        if ($p.Name -notmatch $NamePattern) { return $false }
        if ($Match -and (-not $p.CommandLine -or $p.CommandLine -notmatch $Match)) { return $false }
    } catch { return $false }
    return $true
}

$script:Procs = @{}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object { $script:Procs[[int]$_.ProcessId] = $_ }
function Test-ClaudeSessionOwned([int]$ProcId) {
    $cur = $script:Procs[$ProcId]
    for ($i = 0; $i -lt 4 -and $cur; $i++) {
        $parent = $script:Procs[[int]$cur.ParentProcessId]
        if (-not $parent) { return $false }
        # PID reuse: an "ancestor" that started after the child is not its ancestor
        if ($parent.CreationDate -gt $cur.CreationDate) { return $false }
        if ($parent.Name -eq "claude.exe") { return $true }
        $cur = $parent
    }
    return $false
}

# Is the process the web app, or something the web app started (collector, workers)?
# Without -All the orphan sweep leaves these alone.
function Test-WebOwned([int]$ProcId) {
    $cur = $script:Procs[$ProcId]
    for ($i = 0; $i -lt 4 -and $cur; $i++) {
        if ($cur.CommandLine -and $cur.CommandLine -match $AppMatch) { return $true }
        $parent = $script:Procs[[int]$cur.ParentProcessId]
        if (-not $parent) { return $false }
        if ($parent.CreationDate -gt $cur.CreationDate) { return $false }
        $cur = $parent
    }
    return $false
}

function Get-PortListenerPid([int]$Port) { return Get-StackPortListenerPid -Port $Port }

# 0. Watchdog
$wd = Join-Path $NotifDir "watchdog.pid"
if (Test-Path $wd) {
    $wdPid = "$(Get-Content $wd -Raw)".Trim()
    if (Test-StackProcess $wdPid '^powershell\.exe$' 'watchdog') { Stop-ProcessTree ([int]$wdPid); Write-Host "  [x] Watchdog" }
    else { Write-Host "  [~] Watchdog: stale pid file ($wdPid), nothing killed" }
    Remove-Item $wd -Force -ErrorAction SilentlyContinue
}

# 1. Memory server, gracefully first
$mp = Get-PortListenerPid $MemoryPort
if ($mp) {
    $shutdown = Join-Path $VaultPath "memory\memory_shutdown.py"
    $global:LASTEXITCODE = 1
    if (Test-Path $shutdown) { & python -X utf8 $shutdown | Out-Null }
    if ($LASTEXITCODE -ne 0 -or (Get-PortListenerPid $MemoryPort)) {
        $mp = Get-PortListenerPid $MemoryPort
        if ($mp -and (Test-StackProcess "$mp" -Match 'memory')) { Stop-ProcessTree ([int]$mp); Write-Host "  [x] Memory (hard kill, graceful failed)" }
        elseif ($mp) { Write-Host "  [!] Port $MemoryPort is held by pid=$mp which is not the memory server, left alone" }
    } else { Write-Host "  [x] Memory (graceful)" }
}

# 2. Daemons by pid file
Get-ChildItem $NotifDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
    # The web app's pid file belongs to step 3, and is kept without -All
    if (-not $All -and $_.BaseName -eq "web") { return }
    $p = "$(Get-Content $_.FullName -Raw)".Trim()
    if (-not (Test-StackProcess $p)) {
        if (($p -match '^\d+$') -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { Write-Host "  [!] $($_.BaseName): pid=$p is another process now, left alone" }
        else { Write-Host "  [~] $($_.BaseName): stale pid file ($p)" }
    } elseif (-not (Test-ClaudeSessionOwned ([int]$p))) { Stop-ProcessTree ([int]$p); Write-Host "  [x] $($_.BaseName)" }
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}
$locks = Get-ChildItem $NotifDir -Filter "*.lock" -ErrorAction SilentlyContinue
if (-not $All) { $locks = @($locks | Where-Object { $_.Name -notlike "web*" }) }
$locks | Remove-Item -Force -ErrorAction SilentlyContinue

# 3. Apps by port (one process may hold both the local and the tunnel port)
if ($All) {
    $seen = @{}
    foreach ($port in $AppPorts) {
        $lp = Get-PortListenerPid $port
        if (-not $lp -or $seen[$lp]) { continue }
        $seen[$lp] = 1
        if (Test-StackProcess "$lp" -Match $AppMatch) { Stop-ProcessTree $lp; Write-Host "  [x] app on port $port" }
        else { Write-Host "  [!] Port $port is held by pid=$lp which is not the web app, left alone" }
    }
} else {
    Write-Host "  [=] web app left up (-All stops it too)"
}

# 4. Orphan sweep
Get-CimInstance Win32_Process -Filter $StackPyWmiFilter -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $VaultRx -and $_.ProcessId -ne $PID } |
    Where-Object { -not (Test-ClaudeSessionOwned $_.ProcessId) } |
    Where-Object { $All -or -not (Test-WebOwned $_.ProcessId) } |
    ForEach-Object { Stop-ProcessTree $_.ProcessId; Write-Host "  [x] orphan pid=$($_.ProcessId)" }

# 5. Tunnel client, only with -All
if ($All) {
    $cf = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
    if ($cf) { foreach ($c in $cf) { Stop-ProcessTree $c.Id }; Write-Host "  [x] tunnel" }
} else {
    Write-Host "  [=] tunnel left up (-All stops it too)"
}

Write-Host "Stack stopped."
