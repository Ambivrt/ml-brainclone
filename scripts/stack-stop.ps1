# stack-stop.ps1 -- stop everything stack-start.ps1 starts. Idempotent.
#
# Order:
#   0. The watchdog first, or it restarts everything else within 60 s.
#   1. The memory server gracefully: it holds an unflushed vector index, and a
#      hard kill has corrupted the index before. Hard kill only as a fallback.
#   2. Daemons by pid file, each with its whole process tree (cmd /c wrappers
#      spawn python; killing the parent alone leaves orphans).
#   3. Apps by port. The port is the truth, the pid file a fallback.
#   4. Orphan sweep: python processes running one of the stack's scripts.
#
# Processes owned by a live Claude Code session are spared. A session's MCP
# servers have claude.exe as an ancestor, and Claude Code never restarts them:
# killed, they stay gone in every open window until /mcp or a restart.

$VaultPath = $env:VAULT_ROOT
if (-not $VaultPath) { Write-Error "VAULT_ROOT not set"; exit 1 }
$NotifDir = Join-Path $VaultPath ".notifications"
$MemoryPort = 18923
$AppPorts = @(8801, 8800)

function Stop-ProcessTree([int]$ProcId) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcId" -ErrorAction SilentlyContinue |
        ForEach-Object { if ($_.ProcessId -ne $PID) { Stop-ProcessTree $_.ProcessId } }
    if ($ProcId -ne $PID) { Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue }
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

function Get-PortListenerPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess } else { return $null }
}

# 0. Watchdog
$wd = Join-Path $NotifDir "watchdog.pid"
if (Test-Path $wd) { Stop-ProcessTree ([int](Get-Content $wd -Raw).Trim()); Remove-Item $wd -Force -ErrorAction SilentlyContinue; Write-Host "  [x] Watchdog" }

# 1. Memory server, gracefully first
$mp = Get-PortListenerPid $MemoryPort
if ($mp) {
    $shutdown = Join-Path $VaultPath "memory\memory_shutdown.py"
    $global:LASTEXITCODE = 1
    if (Test-Path $shutdown) { & python -X utf8 $shutdown | Out-Null }
    if ($LASTEXITCODE -ne 0 -or (Get-PortListenerPid $MemoryPort)) { Stop-ProcessTree $mp; Write-Host "  [x] Memory (hard kill, graceful failed)" }
    else { Write-Host "  [x] Memory (graceful)" }
}

# 2. Daemons by pid file
Get-ChildItem $NotifDir -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
    $p = (Get-Content $_.FullName -Raw).Trim()
    if ($p -match '^\d+$' -and -not (Test-ClaudeSessionOwned ([int]$p))) { Stop-ProcessTree ([int]$p); Write-Host "  [x] $($_.BaseName)" }
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}
Get-ChildItem $NotifDir -Filter "*.lock" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

# 3. Apps by port (one process may hold both the local and the tunnel port)
$seen = @{}
foreach ($port in $AppPorts) {
    $lp = Get-PortListenerPid $port
    if ($lp -and -not $seen[$lp]) { $seen[$lp] = 1; Stop-ProcessTree $lp; Write-Host "  [x] app on port $port" }
}

# 4. Orphan sweep
$root = [regex]::Escape($VaultPath)
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $root -and -not (Test-ClaudeSessionOwned $_.ProcessId) } |
    ForEach-Object { Stop-ProcessTree $_.ProcessId; Write-Host "  [x] orphan pid=$($_.ProcessId)" }

Write-Host "Stack stopped."
