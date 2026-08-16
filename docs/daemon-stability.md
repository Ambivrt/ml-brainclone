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

**Prefer a control channel over a kill.** `kill` skips whatever flush the singleton owes its database. For an HNSW vector index that means the on-disk index can diverge from its metadata store, after which vector search silently degrades to keyword fallback and nothing logs an error. Give the singleton a control message it obeys only when it runs headless, and fall back to the hard kill only when it does not answer:

```python
# In the singleton's connection handler, BEFORE the request lock.
# Checking it ahead of the lock is what makes shutdown reachable while a
# hung request holds the lock -- which is exactly when you need it.
if request.get("control") == "shutdown":
    if headless:
        wfile.write(json.dumps({"ok": True}) + "\n"); wfile.flush()
        shutdown.set()
        return
    # A session-owned singleton refuses; its owner decides its lifetime.
    wfile.write(json.dumps({"ok": False, "error": "session-owned"}) + "\n")
```

```bash
python shutdown_singleton.py          # 0 = down, 2 = refused, 3 = no response
if [ $? -ne 0 ]; then
    kill $SINGLETON_PIDS 2>/dev/null || true    # fallback only
fi
```

**Key insight:** The singleton pattern (#8) and this pattern work together. The singleton prevents accidental concurrent access during normal operation. But batch jobs that need exclusive access must deliberately shut the singleton down first. Both patterns are necessary, neither alone is sufficient.

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

> Format is the easy half. What the heartbeat is allowed to *mean* is the hard half -- see #17 before wiring a health check to any of this.

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

A PID check alone only catches daemons that died. Daemons that hang keep their PID, their port, and their file handles -- so the watchdog must also judge heartbeat age, and the heartbeat must be worth judging (#17).

**Key design decisions:**
- Uses the same daemon registry as start-all/stop-all (pattern #4)
- Writes its own PID file so start-all can detect if it's already running
- Logs every restart to `watchdog.log` for audit
- Does NOT restart itself — the OS Task Scheduler or start-all handles watchdog crashes
- Max heartbeat age is per daemon, not one global constant (#17)
- Daemons holding unflushed state are shut down through their control channel before any hard kill (#9)
- Honors a maintenance flag so planned exclusive-access jobs are not fought by an eager restart; cap the flag's age so a crashed batch job cannot disable recovery forever

See `scripts/watchdog.ps1` for the reference implementation.

---

### 15. Protect Daemons from Accidental Mass-Kill

> **Note:** In practice, the singleton + watchdog + circuit breaker stack (see "Runtime Integration" below) handles most of this. The hook approach below works but generates false positives on legitimate commands that mention daemon names (e.g., `git diff larry-stop.ps1`). Consider whether your runtime defenses are sufficient before adding command interception.

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

### 17. Heartbeats Must Prove Responsiveness, Not Liveness

**Problem:** A heartbeat written by a dedicated thread proves one thing: that thread is scheduled. It says nothing about whether the daemon can still do its job. A server that accepts TCP connections but never answers them keeps writing a perfectly fresh heartbeat while every caller hangs. The watchdog (#14) sees a healthy daemon and never restarts it. This is worse than no heartbeat at all, because it actively suppresses recovery.

This failure mode is common in daemons that serialize work behind a lock: a request that never returns holds the lock forever, every subsequent request queues behind it, and the heartbeat thread -- which touches neither the lock nor the work -- keeps ticking.

**Fix:** The heartbeat must be the *result* of a completed round trip, not a timer. Have the daemon call itself through the same path a real client uses -- socket, accept loop, handler thread, lock, business logic -- and write the heartbeat file only when a response comes back.

```python
PROBE_INTERVAL = 30
PROBE_TIMEOUT = 60
PROBE_ID = "self-probe"

def probe_once(timeout):
    """Call ourselves over the wire. Returns (ok, rtt, detail)."""
    req = {"jsonrpc": "2.0", "id": PROBE_ID, "method": "<cheap real method>"}
    t0 = time.monotonic()
    sock = None
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
        sock.settimeout(timeout)          # the probe must never hang either
        sock.makefile("w").write(json.dumps(req) + "\n")
        line = sock.makefile("r").readline()
        if not line:
            return False, time.monotonic() - t0, "closed without answering"
        resp = json.loads(line)
        return resp.get("id") == PROBE_ID, time.monotonic() - t0, "ok"
    except (socket.timeout, TimeoutError):
        return False, time.monotonic() - t0, f"no answer within {timeout}s"
    except (OSError, json.JSONDecodeError) as e:
        return False, time.monotonic() - t0, str(e)
    finally:
        if sock:
            sock.close()

def heartbeat_loop(stop_event):
    write_heartbeat("probe=startup")      # grace while the daemon warms up
    while not stop_event.wait(PROBE_INTERVAL):
        ok, rtt, detail = probe_once(PROBE_TIMEOUT)
        if ok:
            write_heartbeat(f"probe=ok rtt={rtt:.2f}s")
        else:
            log.error("self-probe FAILED: %s -- withholding heartbeat", detail)
            # No write. The file ages out and the watchdog takes over.
```

**Count an error response as alive.** What the probe measures is responsiveness, not correctness. If a valid error reply is treated as failure, an empty database or a degraded-but-working backend puts the watchdog into a restart loop -- and restart loops during degradation are how a recoverable problem becomes an outage. A server that answers "I cannot do that" is a server that is answering.

**Set the watchdog's max-age per daemon, not globally.** A heartbeat that costs a round trip deserves a tighter bound than one written blindly. Six missed probes is a silent server; ten minutes of generic grace is a wasted outage.

```powershell
@{
    Name     = "mcp-server"
    Port     = 18923
    HbMaxAge = 180          # probe runs every 30s -- 180s = six missed proofs
    GracefulStop = $true    # see #9: flush before you kill
}
```

**Rule:** A heartbeat answers "can you still serve?", not "is a thread running?". If it cannot fail, it is not a health check.

---

### 18. Every Proxy Needs a Client-Side Timeout

**Problem:** A proxy that forwards lines between a client and a backend usually blocks forever on read -- `settimeout(None)` is the default after connect, and it feels correct because the backend "always" answers. When the backend stops answering, the client has no way to find out. It waits until whatever outer limit exists finally fires. A 30-minute tool timeout is not a timeout; it is a session that dies quietly.

Restarting the backend does not help. The client's channel is still bound to the dead process, so every call after the restart hangs exactly like the ones before it.

**Fix:** Track in-flight request IDs in the proxy. When one exceeds the timeout, answer the client yourself with a protocol-level error, tear down the connection, and reconnect. Three details make this correct:

1. **Never register notifications.** Messages without an ID get no response by design; booking them as outstanding guarantees a false timeout.
2. **Drop late replies for abandoned IDs.** If the backend answers after you already replied, forwarding it sends the client two responses for one request.
3. **Answer everything still in flight when the socket dies**, not just what timed out. Otherwise a broken connection leaves calls hanging with nobody left to answer them.

```python
CLIENT_TIMEOUT = 120

pending = {}       # request-id -> monotonic timestamp
abandoned = set()  # answered locally; drop the backend's late reply

def note_request(raw):
    msg = json.loads(raw)
    if "method" not in msg or msg.get("id") is None:
        return                       # notification -- never gets a reply
    with state_lock:
        pending[msg["id"]] = time.monotonic()

def note_response(raw):
    """Returns False if the line should be dropped."""
    msg = json.loads(raw)
    rid = msg.get("id")
    with state_lock:
        pending.pop(rid, None)
        if rid in abandoned:
            abandoned.discard(rid)
            return False
    return True

def timeout_guard(sock):
    while not stop.wait(1.0):
        now = time.monotonic()
        with state_lock:
            expired = [r for r, t in pending.items() if now - t > CLIENT_TIMEOUT]
            for r in expired:
                del pending[r]
                abandoned.add(r)
        for rid in expired:
            emit({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32001,
                            "message": f"backend did not answer within {CLIENT_TIMEOUT}s"}})
        if expired:
            sock.shutdown(socket.SHUT_RDWR)   # force reconnect on the next call
            return
```

Keep the outer limit too, set slightly above the proxy's own, so the proxy's clean error wins and the outer one only catches the proxy itself failing.

**Testing this is easy and worth it.** Stand up a fake backend that accepts connections and answers nothing, run the real proxy against it as a subprocess, and assert that an error comes back within seconds. That test fails loudly on any regression that reintroduces the hang.

**Rule:** Any blocking call across a process boundary needs a deadline. "It always answers" is an assumption, not a property.

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
11. Make the heartbeat conditional on a completed self-probe, and set the daemon's own max-age in the watchdog registry (#17)
12. If the daemon serves other processes, give the client side a timeout and a reconnect path (#18)
13. If the daemon holds unflushed state, add a control-channel shutdown and use it before any kill (#9)
14. Register in Windows Task Scheduler for autostart (AtLogon trigger)
15. Add to Darry's Light Sleep heartbeat check list

---

## Runtime Integration: How the Patterns Compose

The patterns above are taught individually but deployed together. Here is how the running system wires them into three layers of protection against process explosion and silent death.

### Layer 1: Daemon Singleton (file lock + PID)

Every daemon acquires an exclusive file lock at startup via a shared `daemon_singleton.py` module. This is stricter than the PID-check singleton in #8: a file lock is released by the OS when the process dies, so stale PID files cannot fool it.

```python
# daemon_singleton.py (simplified)
import fcntl, os, sys
from pathlib import Path

class DaemonSingleton:
    def __init__(self, name: str, notif_dir: Path):
        self.lock_path = notif_dir / f"{name}.lock"
        self.pid_path  = notif_dir / f"{name}.pid"
        self._fd = None

    def acquire(self):
        self._fd = open(self.lock_path, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{self.lock_path.stem}] already running -- exiting")
            sys.exit(0)
        self.pid_path.write_text(str(os.getpid()))

    def release(self):
        self.pid_path.unlink(missing_ok=True)
        if self._fd:
            self._fd.close()
```

On Windows, replace `fcntl.flock` with `msvcrt.locking`. The principle is the same: the OS guarantees mutual exclusion, not your code.

### Layer 2: Watchdog Circuit Breaker

The watchdog (#14) tracks consecutive restart failures per daemon. After a configurable number of failures (default: 3) it writes a `.circuit-broken` flag file and stops trying. This prevents restart storms where a daemon with a persistent error (missing dependency, corrupt state) consumes all watchdog cycles.

```
notifications/
    tarry.circuit-broken     <-- watchdog stops retrying tarry
    tarry.pid                <-- stale, process is dead
```

The start script (`larry-start.ps1`) clears all `.circuit-broken` flags on a full restart, so a manual restart always resets the breaker.

### Layer 3: Per-Daemon Disable

A `.disabled` flag file tells the watchdog to skip a daemon entirely. Useful for planned maintenance, debugging, or temporarily removing a daemon from the stack without editing the registry.

```powershell
# Disable vibesensor -- watchdog will ignore it
"" | Out-File notifications\vibesensor.disabled

# Re-enable (or run larry-start.ps1 which clears all flags)
Remove-Item notifications\vibesensor.disabled
```

### How the layers interact

```
Daemon starts
    |
    v
Singleton lock acquired?
    |            |
   YES          NO --> exit immediately (another instance holds the lock)
    |
    v
Daemon runs, writes heartbeats
    |
    v
Daemon dies (crash, OOM, unhandled exception)
    |
    v
OS releases file lock automatically
    |
    v
Watchdog detects missing heartbeat or dead PID
    |
    v
Is .disabled set? --> YES --> skip, log, move on
    |
    NO
    |
    v
Is .circuit-broken set? --> YES --> skip, log, move on
    |
    NO
    |
    v
Restart daemon
    |
    v
Did it survive the liveness check?
    |            |
   YES          NO --> increment failure counter
    |                    |
    v                    v
  Reset counter     counter >= 3? --> write .circuit-broken, notify
```

This three-layer defense means:
- **No duplicate processes** (singleton lock)
- **No restart storms** (circuit breaker)
- **No fighting planned maintenance** (disable flag)
- **Full reset on manual restart** (start script clears all flags)

---

## See Also

- [larry-setup.md](larry-setup.md) -- Larry configuration and startup
- [parry-setup.md](parry-setup.md) -- Parry daemon (gatekeeper)
- [tarry-setup.md](tarry-setup.md) -- Tarry daemon (time)
- [carry-setup.md](carry-setup.md) -- Carry daemon (logistics)
- [darry-setup.md](darry-setup.md) -- Darry daemon (nightly processing)
- [brains-bus-setup.md](brains-bus-setup.md) -- Inter-agent event bus
- [logging-architecture.md](logging-architecture.md) -- Save-everything logging
