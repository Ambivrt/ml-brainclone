# Daemon Stability — Patterns and Antipatterns

Hard-won lessons from running a multi-daemon AI agent ecosystem on Windows. These patterns apply to any long-running Python daemon managed by Windows Task Scheduler (or systemd on Linux), especially when multiple daemons share a filesystem, bus, and logging infrastructure.

---

## Critical Patterns

### 1. No Non-ASCII in PowerShell Start Scripts

**Problem:** PowerShell 5.1 (the default on Windows 10/11) crashes or garbles `.ps1` files containing non-ASCII characters (em-dashes, accented characters, Unicode symbols) when they are saved as UTF-8 without BOM.

**Fix:** Never use non-ASCII in `.ps1` files. Replace em-dashes (`---`) with double hyphens (`--`), accented characters with ASCII equivalents in comments, and Unicode symbols with ASCII art. If you need Unicode in log output, emit it from Python, not from the start script.

```powershell
# BAD -- PowerShell 5.1 may crash on this file
# Startar daemon -- kontrollerar status

# GOOD
# Starts daemon -- checks status
```

**Rule:** PowerShell start scripts are plumbing. Keep them ASCII-only.

---

### 2. Don't Fight Python for Log Ownership

**Problem:** Start scripts that redirect stdout (`-RedirectStandardOutput $LogFile`) to the same file a Python `RotatingFileHandler` writes to will produce garbled or lost log entries. Two processes writing to the same file without coordination corrupts both outputs.

**Fix:** Let Python own its own log files via `logging.handlers.RotatingFileHandler`. The start script should only redirect stderr (for crash tracebacks that happen before Python's logging initializes).

```powershell
# BAD -- both PowerShell and Python write to the same file
Start-Process pythonw -ArgumentList "daemon.py" `
    -RedirectStandardOutput "daemon.log" `
    -RedirectStandardError "daemon-err.log"

# GOOD -- only redirect stderr for pre-init crashes
Start-Process pythonw -ArgumentList "daemon.py" `
    -RedirectStandardError "daemon-startup-err.log"
```

Python handles the rest:
```python
import logging
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    "daemon.log", maxBytes=5_000_000, backupCount=3
)
logging.basicConfig(handlers=[handler], level=logging.INFO)
```

---

### 3. Circuit Breakers Must Notify Before Dying

**Problem:** Daemons with circuit breakers (e.g., "exit after 5 consecutive errors") that just call `sys.exit(1)` die silently. Nobody knows they stopped. Their responsibilities go unmet until someone manually checks.

**Fix:** Before exiting, the daemon must:
1. Post a crash event on the bus (so other agents know)
2. Write a crash flag file (so health checks can detect it without polling the bus)
3. Send a notification to the user (Telegram, email, whatever your notification channel is)

```python
MAX_CONSECUTIVE_ERRORS = 5

def circuit_breaker_exit(error_count: int, last_error: str):
    """Notify everything, then die."""
    crash_info = {
        "daemon": DAEMON_NAME,
        "error_count": error_count,
        "last_error": last_error,
        "timestamp": datetime.now().isoformat(),
    }

    # 1. Bus event
    try:
        post_bus_event(
            from_=DAEMON_NAME, to="*",
            kind="daemon-crash",
            payload=crash_info,
        )
    except Exception:
        pass  # Bus might be down too

    # 2. Crash flag file (survives bus failures)
    crash_flag = HEARTBEAT_DIR / f"{DAEMON_NAME}.crashed"
    crash_flag.write_text(json.dumps(crash_info))

    # 3. User notification
    try:
        send_notification(f"{DAEMON_NAME} crashed after {error_count} consecutive errors: {last_error}")
    except Exception:
        pass

    sys.exit(1)
```

**Rule:** A daemon that dies silently is worse than a daemon that crashes loudly.

---

### 4. Every Daemon in Both Start-All and Stop-All

**Problem:** A daemon that is registered in `start-all` but not in `stop-all` accumulates zombie processes on restart. You restart the ecosystem, the old process keeps running, and now you have two instances fighting over the same queue/heartbeat file.

**Fix:** Maintain a single canonical list of all managed daemons. Both start-all and stop-all scripts iterate the same list. When you add a new daemon, you add it to one place.

```python
# daemon_registry.py -- single source of truth
MANAGED_DAEMONS = [
    {"name": "parry",  "script": "parry/parry_guardian.py",  "heartbeat": "parry-guardian.heartbeat"},
    {"name": "tarry",  "script": "tarry/tarry_service.py",   "heartbeat": "tarry-service.heartbeat"},
    {"name": "carry",  "script": "carry/carry_service.py",   "heartbeat": "carry-service.heartbeat"},
    {"name": "darry",  "script": "darry/darry_service.py",   "heartbeat": "darry-service.heartbeat"},
    {"name": "listener", "script": "notifications/bot_listener.py", "heartbeat": "bot-listener.heartbeat"},
]
```

```python
# daemon_manager.py
from daemon_registry import MANAGED_DAEMONS

def start_all():
    for d in MANAGED_DAEMONS:
        start_daemon(d)

def stop_all():
    for d in MANAGED_DAEMONS:
        stop_daemon(d)
```

**Rule:** If it starts, it must stop. No exceptions.

---

## High-Priority Patterns

### 5. Liveness Check After Launch

**Problem:** Start scripts that call `Start-Process` and immediately report success have no idea if the daemon actually started. A missing dependency, port conflict, or bad config can cause the process to exit within milliseconds.

**Fix:** After launching, wait briefly and check whether the process is still alive. Report failure immediately rather than letting it fail silently.

```powershell
$proc = Start-Process pythonw -ArgumentList "daemon.py" `
    -RedirectStandardError "daemon-err.log" `
    -PassThru

Start-Sleep -Milliseconds 800

if ($proc.HasExited) {
    $exitCode = $proc.ExitCode
    Write-Host "[FAIL] Daemon exited immediately (code $exitCode)" -ForegroundColor Red
    if (Test-Path "daemon-err.log") {
        Get-Content "daemon-err.log" | Write-Host -ForegroundColor Red
    }
    exit 1
}

Write-Host "[OK] Daemon started (PID: $($proc.Id))"
```

---

### 6. Retry with Backoff, Not Immediate Exit

**Problem:** A daemon that depends on another service (MCP server, database, bus) and calls `sys.exit(1)` when the dependency is unavailable creates a fragile startup order. If the dependency restarts, the dependent daemon stays dead.

**Fix:** Use exponential backoff with a maximum retry count. This handles transient failures (service restarting) without infinite loops.

```python
import time

MAX_RETRIES = 5
BASE_DELAY = 2  # seconds

def connect_with_backoff(connect_fn, service_name: str):
    for attempt in range(MAX_RETRIES):
        try:
            return connect_fn()
        except ConnectionError as e:
            delay = BASE_DELAY * (2 ** attempt)
            logging.warning(
                f"{service_name} unavailable (attempt {attempt + 1}/{MAX_RETRIES}), "
                f"retrying in {delay}s: {e}"
            )
            time.sleep(delay)

    # All retries exhausted
    circuit_breaker_exit(MAX_RETRIES, f"Could not connect to {service_name}")
```

---

### 7. Never Hardcode Python Paths

**Problem:** Start scripts that hardcode `python.exe` or `C:\Python310\python.exe` break when Python is upgraded, when a venv is used, or when the system is set up differently from the developer's machine.

**Fix:** In Python code, use `sys.executable` to find the current interpreter. In PowerShell start scripts, either rely on `PATH` or make the path configurable.

```python
import sys
import subprocess

# BAD
subprocess.Popen(["python", "child_script.py"])
subprocess.Popen(["C:\\Python310\\python.exe", "child_script.py"])

# GOOD -- uses the same interpreter that's running this script
subprocess.Popen([sys.executable, "child_script.py"])
```

```powershell
# GOOD -- configurable, with fallback
$Python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "pythonw.exe" }
Start-Process $Python -ArgumentList "daemon.py"
```

---

### 8. Singleton Guards for Standalone Entrypoints

**Problem:** Daemons launched by Task Scheduler can sometimes be triggered twice (manual run during scheduled run, scheduler retry on perceived failure, user starting it from CLI while it is already running). Two instances of the same daemon corrupt shared state.

**Fix:** Check for an existing PID file or process at startup. Exit cleanly if another instance is already running.

```python
import os
import sys
from pathlib import Path

PID_FILE = Path("daemon.pid")

def acquire_singleton():
    if PID_FILE.exists():
        old_pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(old_pid, 0)  # Check if process exists
            print(f"Already running (PID {old_pid}). Exiting.")
            sys.exit(0)
        except OSError:
            pass  # Old process is dead, take over

    PID_FILE.write_text(str(os.getpid()))

def release_singleton():
    PID_FILE.unlink(missing_ok=True)
```

Call `acquire_singleton()` at the top of `main()` and `release_singleton()` in a `finally` block or `atexit` handler.

---

## Medium-Priority Patterns

### 9. Kill Singletons Before Exclusive Resource Access

**Problem:** A background MCP server (or any singleton process) holds an exclusive lock on a database (e.g., ChromaDB HNSW index). When a batch job needs to access the same database, it deadlocks — the batch waits for the lock, the singleton never releases it, and the batch runner's timeout kills everything. No output is produced. No error is logged.

**Fix:** Before a batch job that needs exclusive database access, kill the singleton process that holds the lock. The singleton restarts automatically on the next MCP call.

```bash
# Kill singleton before exclusive access (e.g., reindexing)
SINGLETON_PIDS=$(pgrep -f "my-singleton" 2>/dev/null || true)
if [ -n "$SINGLETON_PIDS" ]; then
    echo "Killing singleton (pids: $SINGLETON_PIDS) for exclusive DB access"
    echo "$SINGLETON_PIDS" | xargs kill 2>/dev/null || true
    sleep 2  # Wait for file handles to release
fi

# Now safe to access the database exclusively
timeout 300 python -m my_indexer mine "$VAULT" || echo "Indexing failed (continuing)"
```

**Key insight:** The singleton pattern (#8) and this pattern work together. The singleton prevents accidental concurrent access during normal operation. But batch jobs that need exclusive access must deliberately kill the singleton first. Both patterns are necessary — neither alone is sufficient.

**Real-world scenario:** A nightly indexer (mempalace mine) needs exclusive access to ChromaDB. The MCP singleton proxy holds the HNSW index open. Without killing the singleton first, the indexer deadlocks. The batch runner's 30-minute timeout kills the process, and all subsequent batches that depend on updated indexes produce no output. The failure is completely silent — no error in the log, just missing output files.

---

### 10. PATH Hardening for Batch Runners on Windows

**Problem:** On Windows, `bash` in PATH may resolve to a WSL shim (`WindowsApps/bash.exe`) instead of Git Bash (`/usr/bin/bash`). When Windows Task Scheduler runs a bash script, the WSL shim intercepts the call, and the script runs in a different environment (wrong Python, wrong tools, wrong filesystem paths). Everything fails silently because the WSL environment has none of your tools installed.

**Fix:** In batch runner scripts, explicitly prepend the correct `bash` location to PATH and remove the WindowsApps directory. Do this at the top of every script that Task Scheduler might call.

```bash
#!/bin/bash
# PATH hardening -- defense in depth for Task Scheduler
# Git Bash's /usr/bin MUST come first. WindowsApps contains a WSL bash shim
# that hijacks `bash` calls and routes them to a different environment.
export PATH="/usr/bin:/c/Users/$USER/.local/bin:/c/Program Files/nodejs:/c/Program Files/Git/bin:$PATH"
export PYTHONIOENCODING=utf-8
```

**Why this is insidious:** The WSL shim does not produce an error. It launches WSL, which has its own `python3`, its own PATH, and no access to your Windows tools. Your script runs, but in the wrong universe. Logs show successful execution with zero useful output.

**Detection:** If your scheduled batch suddenly produces empty output files, check `which bash` from the Task Scheduler context. If it resolves to `WindowsApps`, this is your problem.

---

### 11. Consistent Heartbeat Format

**Problem:** If some daemons write heartbeat files as JSON (`{"ts": "...", "state": "..."}`) and others write plaintext ISO8601 timestamps, every health checker must handle both formats. This adds complexity and creates parsing bugs.

**Fix:** Pick one format and enforce it everywhere. JSON is recommended because it is extensible:

```json
{
    "ts": "2026-05-01T14:30:00",
    "pid": 12345,
    "state": "idle",
    "uptime_s": 3600,
    "last_action": "processed 3 queue items"
}
```

Shared heartbeat writer:

```python
import json
from datetime import datetime
from pathlib import Path

def write_heartbeat(heartbeat_path: Path, state: str = "idle", extra: dict = None):
    data = {
        "ts": datetime.now().isoformat(),
        "pid": os.getpid(),
        "state": state,
    }
    if extra:
        data.update(extra)
    heartbeat_path.write_text(json.dumps(data))
```

Health checker:

```python
def check_heartbeat(heartbeat_path: Path, max_age_seconds: int = 120) -> bool:
    if not heartbeat_path.exists():
        return False
    try:
        data = json.loads(heartbeat_path.read_text())
        ts = datetime.fromisoformat(data["ts"])
        return (datetime.now() - ts).total_seconds() < max_age_seconds
    except (json.JSONDecodeError, KeyError, ValueError):
        return False
```

---

### 12. Stop Scripts Should Only Clean Up Their Own Heartbeats

**Problem:** A stop-all script that deletes every `.heartbeat` file in a directory can accidentally kill heartbeats belonging to other subsystems (NAS sync, backup monitors, external tools).

**Fix:** Only delete heartbeat files for daemons in the managed registry. Use the registry as the filter.

```python
def stop_all():
    for d in MANAGED_DAEMONS:
        stop_daemon(d)
        heartbeat = HEARTBEAT_DIR / d["heartbeat"]
        heartbeat.unlink(missing_ok=True)
    # Do NOT: glob("*.heartbeat") and delete everything
```

---

### 13. Use pythonw on Windows

**Problem:** Starting daemons with `python.exe` on Windows opens a console window that flickers and steals focus. If the daemon is started by Task Scheduler or from a startup script, the console window is either visible and annoying or minimized and confusing.

**Fix:** Use `pythonw.exe` for background daemons on Windows. It runs without a console window.

```powershell
# BAD -- console window flicker
Start-Process python -ArgumentList "daemon.py"

# GOOD -- no console window
Start-Process pythonw -ArgumentList "daemon.py"
```

In `daemon-manager.py`:
```python
import sys
import platform

def get_python_executable():
    if platform.system() == "Windows":
        # pythonw = same interpreter, no console window
        return sys.executable.replace("python.exe", "pythonw.exe")
    return sys.executable
```

---

## Start Script Template

Combining all the patterns above into a reusable start script template:

```powershell
# start-<daemon>.ps1 -- Start script template
# Patterns applied: ASCII-only, stderr-only redirect, liveness check, singleton

param(
    [string]$VaultPath = "{{VAULT_PATH}}"
)

$ErrorActionPreference = "Stop"

$DaemonName = "my-daemon"
$ScriptPath = "$VaultPath\03-projects\my-daemon\my_daemon_service.py"
$ErrLog     = "$VaultPath\03-projects\my-daemon\startup-err.log"
$PidFile    = "$VaultPath\03-projects\my-daemon\$DaemonName.pid"

# --- Singleton check ---
if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -Raw
    $oldProc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($oldProc -and -not $oldProc.HasExited) {
        Write-Host "[--] $DaemonName already running (PID $oldPid)"
        exit 0
    }
}

# --- Launch ---
$Python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "pythonw.exe" }

$proc = Start-Process $Python -ArgumentList $ScriptPath `
    -WorkingDirectory $VaultPath `
    -RedirectStandardError $ErrLog `
    -PassThru

# --- Liveness check ---
Start-Sleep -Milliseconds 800

if ($proc.HasExited) {
    Write-Host "[FAIL] $DaemonName exited immediately (code $($proc.ExitCode))" -ForegroundColor Red
    if (Test-Path $ErrLog) {
        Get-Content $ErrLog | Write-Host -ForegroundColor Red
    }
    exit 1
}

# --- Record PID ---
$proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
Write-Host "[OK] $DaemonName started (PID $($proc.Id))"
```

---

## Stop Script Template

```powershell
# stop-<daemon>.ps1 -- Stop script template

param(
    [string]$VaultPath = "{{VAULT_PATH}}"
)

$DaemonName = "my-daemon"
$PidFile    = "$VaultPath\03-projects\my-daemon\$DaemonName.pid"
$Heartbeat  = "$VaultPath\03-projects\my-daemon\$DaemonName.heartbeat"

if (-not (Test-Path $PidFile)) {
    Write-Host "[--] $DaemonName not running (no PID file)"
    exit 0
}

$pid = Get-Content $PidFile -Raw
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue

if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $pid -Force
    Write-Host "[OK] $DaemonName stopped (PID $pid)"
} else {
    Write-Host "[--] $DaemonName was not running (stale PID file)"
}

# Clean up
Remove-Item $PidFile -ErrorAction SilentlyContinue
Remove-Item $Heartbeat -ErrorAction SilentlyContinue
```

---

### 14. Watchdog Process for Auto-Recovery

**Problem:** If a daemon crashes and nobody restarts it, its responsibilities go unmet. The user may not notice for hours (especially when away from the machine). The circuit breaker (#3) notifies, but doesn't heal.

**Fix:** Run a dedicated watchdog process that polls all daemon PID files every 60 seconds. If a daemon's PID file is missing or the process behind it is dead, the watchdog clears stale files and restarts it automatically.

```powershell
# watchdog.ps1 -- runs as a hidden background process
while ($true) {
    foreach ($d in $daemons) {
        $alive = Test-DaemonAlive -PidFile $d.PidFile
        if (-not $alive) {
            Clear-StaleFiles -PidFile $d.PidFile -LockFile $d.LockFile
            Restart-Daemon -Daemon $d
        }
    }
    Start-Sleep -Seconds 60
}
```

Integrate into your start-all script so it launches automatically:

```powershell
# At the end of larry-start.ps1
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File watchdog.ps1" -WindowStyle Hidden
```

**Key design decisions:**
- Uses the same daemon registry as start-all/stop-all (pattern #4)
- Writes its own PID file so start-all can detect if it's already running
- Logs every restart to `watchdog.log` for audit
- Does NOT restart itself — the OS Task Scheduler or start-all handles watchdog crashes

See `scripts/watchdog.ps1` for the reference implementation.

---

### 15. Protect Daemons from Accidental Mass-Kill

**Problem:** The AI agent (or a careless script) can run `taskkill /IM pythonw.exe` or `Stop-Process -Name python` and kill every daemon at once. If the user is remote, nothing restarts until they return.

**Fix:** Add a PreToolUse hook that intercepts shell commands and blocks patterns that would mass-kill daemons:

```bash
#!/bin/bash
# protect-daemons.sh -- Claude Code PreToolUse hook
INPUT="$CLAUDE_TOOL_INPUT"

if echo "$INPUT" | grep -qiE 'taskkill.*//(IM|im)\s*(pythonw|python)'; then
  echo "BLOCKED: mass-kill would destroy all daemons." >&2
  exit 2
fi

if echo "$INPUT" | grep -qiE 'Stop-Process.*(-Name|ProcessName)\s*(pythonw?|"pythonw?")'; then
  echo "BLOCKED: Stop-Process -Name python kills all daemons." >&2
  exit 2
fi

exit 0
```

Register in `.claude/settings.json`:
```json
{
  "matcher": "Bash|PowerShell",
  "hooks": [{ "type": "command", "command": "bash hooks/protect-daemons.sh" }]
}
```

**Rule:** The agent can kill a specific PID if asked. It cannot kill all Python processes at once.

---

### 16. Stop Scripts Must Never Kill Desktop Applications

**Problem:** A stop-all script that also kills desktop applications (browser, IDE, file manager, tunnel agents) will destroy the user's working session when `start-all -Force` is run. The user runs `-Force` expecting a clean daemon restart -- instead they lose their browser tabs, editor state, and tunnel connections.

**Fix:** Stop scripts should only kill processes they started. Desktop applications (browser, Obsidian, Claude Code, cloudflared, etc.) are started by the user or OS, not by the daemon manager. They do not belong in the stop-all scope.

```powershell
# BAD -- kills desktop apps during daemon restart
$desktopApps = @("msedge", "Obsidian", "claude", "cloudflared")
foreach ($app in $desktopApps) {
    Get-Process -Name $app | Stop-Process -Force
}

# GOOD -- only kill processes from the daemon registry
foreach ($d in $daemons) {
    $pidPath = Join-Path $NotifDir $d.PidFile
    if (Test-Path $pidPath) {
        $pid = (Get-Content $pidPath -Raw).Trim()
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}
```

**Rule:** If the daemon manager didn't start it, the daemon manager doesn't stop it. Desktop apps may be listed in start-all (for convenience), but never in stop-all.

---

## Checklist for Adding a New Daemon

1. Add to `daemon_registry.py` (or equivalent central list)
2. Create `start-<name>.ps1` from the template above
3. Create `stop-<name>.ps1` from the template above
4. Verify `daemon-manager.py start-all` includes the new daemon
5. Verify `daemon-manager.py stop-all` includes the new daemon
6. Add to the watchdog daemon list (`scripts/watchdog.ps1`)
7. Implement singleton guard in the Python entrypoint
8. Implement circuit breaker with notification (if applicable)
9. Use `RotatingFileHandler` for logging (not stdout redirect)
10. Write heartbeats in JSON format to the standard heartbeat directory
11. Register in Windows Task Scheduler for autostart (AtLogon trigger)
12. Add to Darry's Light Sleep heartbeat check list

---

## See Also

- [larry-setup.md](larry-setup.md) -- Larry configuration and startup
- [parry-setup.md](parry-setup.md) -- Parry daemon (gatekeeper)
- [tarry-setup.md](tarry-setup.md) -- Tarry daemon (time)
- [carry-setup.md](carry-setup.md) -- Carry daemon (logistics)
- [darry-setup.md](darry-setup.md) -- Darry daemon (nightly processing)
- [brains-bus-setup.md](brains-bus-setup.md) -- Inter-agent event bus
- [logging-architecture.md](logging-architecture.md) -- Save-everything logging
