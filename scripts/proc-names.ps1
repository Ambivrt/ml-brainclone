# proc-names.ps1 -- dot-sourced by stack-start, stack-stop and watchdog.
#
# Shared process-identity helpers:
#   - Daemons run as ml-<name>.exe: copies of python/pythonw in the Python
#     folder, so each shows up by name in Task Manager and a stop script can tell
#     the stack's own processes from any other python. The deploy step creates
#     the copies; without them everything falls back to python/pythonw.
#   - A port-table fallback for when the OS listener table lies (see below).

# Win32_Process.Name, with .exe
$StackPyNameRx = '^(pythonw?|ml-[a-z0-9-]+)\.exe$'
# Get-Process.ProcessName, without .exe
$StackPyProcRx = '^(pythonw?|ml-[a-z0-9-]+)$'
# WMI filter for every python process of the stack
$StackPyWmiFilter = "Name='python.exe' OR Name='pythonw.exe' OR Name LIKE 'ml-%'"

function Get-StackPythonDir {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($py) { return Split-Path $py -Parent }
    return $null
}

# Named exe for a daemon, otherwise the fallback (python/pythonw).
# $Name is the registry name (for example "Parry", "Task-watcher-larry").
function Get-StackPythonExe {
    param([string]$Name, [string]$Fallback = "pythonw")
    $dir = Get-StackPythonDir
    if ($dir) {
        $named = Join-Path $dir ("ml-" + $Name.ToLower() + ".exe")
        if (Test-Path $named) { return $named }
    }
    return $Fallback
}

# === Port reserve ===
# After some Windows updates Get-NetTCPConnection, netstat and psutil have been
# seen returning only a handful of random listeners: ports that answered fine
# were missing. Start, stop and watchdog then saw the memory server and the web
# app as down, double-started them and tripped circuit breakers.
# The reserve: empty table -> connect test against the port -> find the owner by
# command line. Only the stack's known ports, only the stack's own python
# processes. Anything that kills still verifies the pid first (Test-StackProcess
# in stack-stop, Test-AppProcess in stack-start).
# Keep the ports and script paths in step with the daemon and app registries.
$StackPortOwners = @{
    18923 = 'memory\memory_server.py'
    8801  = 'apps\web\app.py'
    8800  = 'apps\web\app.py'
}

function Test-StackPortOpen {
    param([int]$Port, [int]$TimeoutMs = 1000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait($TimeoutMs)) { return $false }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# Pid of the stack process that holds a known port, or $null.
# Several matches (for example a session-started copy next to the daemon): the
# oldest one, it bound the port first.
function Get-StackPortFallbackPid {
    param([int]$Port)
    $match = $StackPortOwners[$Port]
    if (-not $match) { return $null }
    if (-not (Test-StackPortOpen -Port $Port)) { return $null }
    $needle = $match.ToLowerInvariant()
    $procs = @(Get-CimInstance Win32_Process -Filter $StackPyWmiFilter -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($needle) })
    if ($procs.Count -eq 0) { return $null }
    $pick = $procs | Sort-Object CreationDate | Select-Object -First 1
    return [int]$pick.ProcessId
}

# Pid of whoever listens on a port: the OS table first, the reserve second.
function Get-StackPortListenerPid {
    param([int]$Port)
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -ne 0 } | Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return Get-StackPortFallbackPid -Port $Port
}
