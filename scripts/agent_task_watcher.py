"""agent_task_watcher — one universal watcher process per agent.

Polls 00-inbox/ for task files where frontmatter `agent:` matches --agent.
Atomic claim via rename, then runs the agent's executor, then writes result.
Optionally emits a `task-result` event on a brains-bus so the listener can
push a notification to the user.

Usage:
    python agent_task_watcher.py --agent larry
    python agent_task_watcher.py --agent harry
    python agent_task_watcher.py --agent barry

Guardian-friendly: writes a heartbeat file and PID file, exits cleanly on
SIGTERM. Your supervisor (systemd, a custom Python guardian, or a scheduled
task) is expected to restart it if the heartbeat goes stale.

Configure these environment variables:
    VAULT_ROOT               — vault directory (required)
    AGENT_WATCHER_NOTIF_DIR  — where to write heartbeat/pid/log (default: VAULT_ROOT/.notifications)
    CLAUDE_BIN               — path to Claude CLI (default: "claude")
    BARRY_SCRIPT             — path to barry.py
    HARRY_DIR                — cwd to use when running Harry tasks
    BRAINS_BUS_DIR           — dir containing bus_client.py (optional; no-op if missing)
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import task_lib  # noqa: E402

BUS_DIR = os.environ.get("BRAINS_BUS_DIR")
BUS_AVAILABLE = False
if BUS_DIR and Path(BUS_DIR).exists():
    sys.path.insert(0, BUS_DIR)
    try:
        import bus_client  # noqa: E402
        BUS_AVAILABLE = True
    except Exception:
        BUS_AVAILABLE = False

POLL_SECONDS = 5
HEARTBEAT_EVERY = 15
TASK_TIMEOUT_S = 60 * 30


def _vault_root() -> Path:
    r = os.environ.get("VAULT_ROOT")
    if not r:
        raise SystemExit("VAULT_ROOT env var is required")
    return Path(r)


def _notif_dir() -> Path:
    custom = os.environ.get("AGENT_WATCHER_NOTIF_DIR")
    if custom:
        d = Path(custom)
    else:
        d = _vault_root() / ".notifications"
    d.mkdir(parents=True, exist_ok=True)
    return d


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("watcher")


# ── Executors ────────────────────────────────────────────────────────────────


def _run_subprocess(cmd: list[str], cwd: Path | None = None) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT_S,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
        )
        output = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return {"success": False,
                    "summary": f"exit {proc.returncode}",
                    "detail": output[:2000],
                    "error": err[:1000]}
        summary = output.split("\n\n")[0][:400] if output else "(empty output)"
        return {"success": True, "summary": summary,
                "detail": output[:4000], "error": None}
    except subprocess.TimeoutExpired:
        return {"success": False,
                "summary": f"task exceeded {TASK_TIMEOUT_S}s",
                "detail": "", "error": "TimeoutExpired"}
    except FileNotFoundError as e:
        return {"success": False,
                "summary": f"binary not found: {cmd[0]}",
                "detail": "", "error": str(e)}
    except Exception as e:
        return {"success": False,
                "summary": f"executor error: {type(e).__name__}",
                "detail": "", "error": str(e)}


def executor_larry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    prompt = (
        f"Dispatched task.\n\nTITLE: {title}\n\nDESCRIPTION:\n{desc}\n\n"
        "Do the work. Reply with a short (max 3 sentences) summary of what "
        "you did or what blocked you."
    )
    claude = os.environ.get("CLAUDE_BIN", "claude")
    cmd = [claude, "-p", prompt, "--dangerously-skip-permissions"]
    return _run_subprocess(cmd, cwd=_vault_root())


def executor_harry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    harry_dir = os.environ.get("HARRY_DIR")
    if not harry_dir or not Path(harry_dir).exists():
        return {"success": False, "summary": "HARRY_DIR env var not set or missing",
                "detail": "", "error": "HARRY_DIR unresolved"}
    prompt = (
        f"Dispatched task (Harry context).\n\nTITLE: {title}\n\n"
        f"DESCRIPTION:\n{desc}\n\n"
        "Do the work. Short summary back (max 3 sentences)."
    )
    claude = os.environ.get("CLAUDE_BIN", "claude")
    cmd = [claude, "-p", prompt, "--dangerously-skip-permissions"]
    return _run_subprocess(cmd, cwd=Path(harry_dir))


def executor_barry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    prompt_text = f"{title}. {desc}" if title else desc
    barry_script = os.environ.get("BARRY_SCRIPT")
    if not barry_script or not Path(barry_script).exists():
        return {"success": False, "summary": "BARRY_SCRIPT env var not set or missing",
                "detail": "", "error": "BARRY_SCRIPT unresolved"}
    cmd = [sys.executable, barry_script, prompt_text]
    return _run_subprocess(cmd)


def executor_parry(task: dict) -> dict:
    return {"success": True,
            "summary": "Parry-task noted (gatekeeper events flow over the bus).",
            "detail": f"Input:\n{task['description']}", "error": None}


EXECUTORS = {"larry": executor_larry,
             "harry": executor_harry,
             "barry": executor_barry,
             "parry": executor_parry}


# ── Lifecycle ────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(sig, frame):
    global _running
    log.info(f"signal {sig} — stopping watcher.")
    _running = False


def _write_heartbeat(path: Path, agent: str, state: str = "idle",
                     task_id: str | None = None):
    try:
        path.write_text(json.dumps({
            "pid": os.getpid(), "agent": agent,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "state": state, "task_id": task_id,
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


def _notify(agent: str, task_id: str, result: dict, title: str):
    if not BUS_AVAILABLE:
        return
    try:
        bus_client.emit(  # type: ignore[name-defined]
            kind="task-result",
            payload={"agent": agent, "task_id": task_id, "title": title,
                     "success": result["success"],
                     "summary": result["summary"],
                     "error": result.get("error")},
            to="larry", from_brain=agent,
        )
    except Exception as e:
        log.warning(f"bus emit failed: {e}")


def run(agent: str):
    if agent not in EXECUTORS:
        sys.exit(f"Unknown agent: {agent}")

    notif = _notif_dir()
    hb_path = notif / f"task-watcher-{agent}.heartbeat"
    pid_path = notif / f"task-watcher-{agent}.pid"
    log_path = notif / f"task-watcher-{agent}.log"

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(fh)

    try:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    def _cleanup():
        for p in (pid_path, hb_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    executor = EXECUTORS[agent]
    log.info(f"[{agent}] task-watcher online (pid={os.getpid()})")
    _write_heartbeat(hb_path, agent, "idle")

    last_hb = 0.0
    while _running:
        now = time.time()
        if now - last_hb > HEARTBEAT_EVERY:
            _write_heartbeat(hb_path, agent, "idle")
            last_hb = now

        try:
            pending = task_lib.list_pending_for_agent(agent)
        except Exception as e:
            log.error(f"list_pending error: {e}", exc_info=True)
            pending = []

        for p in pending:
            if not _running:
                break
            try:
                claimed = task_lib.claim_task(p, agent)
            except Exception as e:
                log.error(f"claim error on {p.name}: {e}")
                continue
            if not claimed:
                continue

            try:
                task = task_lib.read_task(claimed)
                task_id = task["meta"].get("task_id", "?")
                log.info(f"[{agent}] claim {task_id}: {task['title']}")
                _write_heartbeat(hb_path, agent, "working", task_id)
                result = executor(task)
                task_lib.complete_task(
                    claimed, agent,
                    success=result["success"],
                    result_summary=result["summary"],
                    result_detail=result.get("detail", ""),
                    error=result.get("error"),
                )
                log.info(f"[{agent}] {task_id} done: success={result['success']}")
                _notify(agent, task_id, result, task["title"])
            except Exception as e:
                log.error(f"executor crash on {claimed.name}: {e}", exc_info=True)
                try:
                    task_lib.complete_task(
                        claimed, agent, success=False,
                        result_summary="watcher crash during execution",
                        error=f"{type(e).__name__}: {e}",
                    )
                except Exception:
                    pass
            finally:
                _write_heartbeat(hb_path, agent, "idle")

        time.sleep(POLL_SECONDS)

    log.info(f"[{agent}] watcher stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True, choices=list(EXECUTORS.keys()))
    args = parser.parse_args()
    if BUS_AVAILABLE:
        os.environ["BRAIN_NAME"] = args.agent
    run(args.agent)
