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
import idempotency  # noqa: E402
from claude_headless import (  # noqa: E402
    FAILURE_CONVENTION, LIMIT_WAIT_30MIN_JOB_S, MCP_WAIT_TOOLS, headless_env, parse_print_output,
)
import session_pool  # noqa: E402
import envelope, protected_files  # noqa: E402

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


def _attempt(task: dict) -> str:
    try:
        return str(int(task.get("meta", {}).get("attempts", 1)) or 1)
    except (TypeError, ValueError):
        return "1"


def _tools_of(task: dict) -> list[str] | None:
    """A tool profile from the task's frontmatter (`tools: [Read, Grep, Edit]`), or None.
    None means full access. A list means only those tools, everything else denied."""
    t = task.get("meta", {}).get("tools")
    if isinstance(t, str):
        t = [x.strip() for x in t.strip("[]").split(",") if x.strip()]
    return t or None


def _loop_denials(session_id: str | None) -> int:
    """Calls the loop guard denied in this session so far (0 if the guard is absent)."""
    if not session_id:
        return 0
    try:
        import loop_guard
        return loop_guard.denials(session_id)
    except Exception:
        return 0


def _run_claude_session(agent: str, prompt: str, cwd: str, task_id: str = "?", attempt: str = "1",
                        allowed_tools: list[str] | None = None, owner: bool = False) -> dict:
    """CLI dispatch with session pooling and JSON output.

    Reuses --resume sessions to skip CLI boot overhead. Falls back to a
    cold start if the session is invalid. Tracks failures and auto-clears
    after MAX_FAILURES consecutive errors (see session_pool.py).

    Model and effort for unattended routine work come from ROUTINE_MODEL and
    ROUTINE_EFFORT, never from the most expensive tier by habit.

    task_id and attempt go into the environment as the idempotency scope, so
    mail sent by the executor gets one key per send and a rerun after a lost
    receipt never sends it again (idempotency.py).

    allowed_tools: None gives full access (--dangerously-skip-permissions). A
    list maps to --allowedTools with --permission-mode dontAsk, so a tool
    outside the profile is denied at once instead of hanging on a prompt
    nobody can answer: tasks never run interactively.

    owner: the task was ordered by the owner themselves, so protected files may
    be changed (protected_files). Tasks from other agents never get that.

    The run waits out usage limits and overload up to a ceiling
    (LIMIT_WAIT_30MIN_JOB_S), and the outcome is honest: is_error, a subtype
    other than success and a TASK-FAILED line are failures even when stdout
    is valid JSON (claude_headless.parse_print_output).
    """
    sid = session_pool.get_session_id(agent)
    claude = os.environ.get("CLAUDE_BIN", "claude")

    cmd = [claude, "--print"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools), "--permission-mode", "dontAsk"]
    else:
        cmd += ["--dangerously-skip-permissions"]
    cmd += [
        "--model", os.environ.get("ROUTINE_MODEL", "opus"),
        "--effort", os.environ.get("ROUTINE_EFFORT", "medium"),
        "--output-format", "json",
        "-p", prompt,
    ]
    if sid:
        cmd.extend(["--resume", sid])

    denials_before = _loop_denials(sid)
    log.info(f"[{agent}] executor: claude ({sid[:8] + '...' if sid else 'new'})")

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=TASK_TIMEOUT_S, encoding="utf-8", errors="replace",
            cwd=cwd,
            # Nobody waits for a task: patient backoff when the API is overloaded
            env=headless_env(MCP_WAIT_TOOLS, {
                "IDEMPOTENCY_SCOPE": f"task:{task_id}",
                "IDEMPOTENCY_ATTEMPT": str(attempt),
                # The owner ordered the task: protected files may be changed
                **({protected_files.OWNER_ENV: "1"} if owner else {}),
            }, patient=True, limit_wait_s=LIMIT_WAIT_30MIN_JOB_S),
        )
        output = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        if proc.returncode != 0 and not output:
            if sid and ("session" in err.lower() or "not found" in err.lower()):
                log.warning(f"[{agent}] invalid session, retrying cold")
                session_pool.clear_session(agent)
                return _run_claude_session(agent, prompt, cwd, task_id, attempt, allowed_tools, owner)
            session_pool.update_session(agent, sid or "", False)
            return {"success": False, "summary": f"exit {proc.returncode}",
                    "detail": output[:2000], "error": err[:1000]}

        # Honest outcome: is_error, a subtype other than success and TASK-FAILED
        # at the end of the reply are failures even when stdout is valid JSON.
        parsed = parse_print_output(output, proc.returncode, job="task-watcher")
        reply = parsed["reply"]
        new_sid = parsed["session_id"]
        session_pool.update_session(agent, new_sid or sid or "", True)
        detail = reply[:4000]
        # The session is pooled across jobs: count only denials from this job
        denied = parsed["loop_denials"] - (denials_before if new_sid == sid else 0)
        if denied > 0:
            detail += f"\n\n[loop guard denied {denied} calls in this job]"
        if not parsed["ok"]:
            return {"success": False, "summary": f"{agent}: {parsed['failure']}"[:400],
                    "detail": detail, "error": parsed["failure"]}
        summary = reply.split("\n\n")[0][:400] if reply else "(empty)"
        return {"success": True, "summary": summary,
                "detail": detail, "error": None}

    except subprocess.TimeoutExpired:
        session_pool.update_session(agent, sid or "", False)
        return {"success": False, "summary": f"exceeded {TASK_TIMEOUT_S}s",
                "detail": "", "error": "TimeoutExpired"}
    except FileNotFoundError:
        return {"success": False, "summary": "claude CLI not found",
                "detail": "", "error": "FileNotFoundError: claude"}
    except Exception as e:
        session_pool.update_session(agent, sid or "", False)
        return {"success": False, "summary": f"{type(e).__name__}",
                "detail": "", "error": str(e)}


def executor_larry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    prompt = (
        f"{envelope.task_header(task['meta'])}\n\nTITLE: {title}\n\nDESCRIPTION:\n{desc}\n\n"
        "Do the work. Reply with a short (max 3 sentences) summary of what "
        "you did or what blocked you."
        + FAILURE_CONVENTION
    )
    return _run_claude_session("larry", prompt, str(_vault_root()), task["meta"].get("task_id", "?"),
                               _attempt(task), _tools_of(task),
                               owner=envelope.task_origin(task["meta"])[1])


def executor_harry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    harry_dir = os.environ.get("HARRY_DIR")
    if not harry_dir or not Path(harry_dir).exists():
        return {"success": False, "summary": "HARRY_DIR env var not set or missing",
                "detail": "", "error": "HARRY_DIR unresolved"}
    prompt = (
        f"{envelope.task_header(task['meta'], 'harry')}\n\nTITLE: {title}\n\n"
        f"DESCRIPTION:\n{desc}\n\n"
        "Do the work. Short summary back (max 3 sentences)."
        + FAILURE_CONVENTION
    )
    return _run_claude_session("harry", prompt, harry_dir, task["meta"].get("task_id", "?"),
                               _attempt(task), _tools_of(task),
                               owner=envelope.task_origin(task["meta"])[1])


def executor_barry(task: dict) -> dict:
    title = task["title"]
    desc = task["description"]
    prompt_text = f"{title}. {desc}" if title else desc
    barry_script = os.environ.get("BARRY_SCRIPT")
    if not barry_script or not Path(barry_script).exists():
        return {"success": False, "summary": "BARRY_SCRIPT env var not set or missing",
                "detail": "", "error": "BARRY_SCRIPT unresolved"}
    # Generation costs credits. The key is stored before the call, so a job rerun
    # after a lost receipt neither generates nor pays a second time.
    key = f"task:{task['meta'].get('task_id', '?')}:barry-generate"
    if not idempotency.claim(key, kind="barry", meta={"title": title}):
        return {"success": False, "summary": "Barry already started in an earlier attempt. Not rerun.",
                "detail": "", "error": f"idempotency key {key} exists, check Barry's inbox"}
    cmd = [sys.executable, barry_script, prompt_text]
    result = _run_subprocess(cmd)
    if result.get("success"):
        idempotency.confirm(key)
    return result


def executor_parry(task: dict) -> dict:
    return {"success": True,
            "summary": "Parry-task noted (gatekeeper events flow over the bus).",
            "detail": f"Input:\n{task['description']}", "error": None}


def executor_tarry(task: dict) -> dict:
    """Tarry task: schedule a reminder or follow-up via tarry_service."""
    title = task["title"]
    desc = task["description"]
    # Tarry tasks skrivs till tarry-queue.json, inte som claude -p
    import json
    from pathlib import Path
    queue_path = Path(_vault_root() / "_private" / "tarry-queue.json")
    try:
        q = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        q = {"reminders": [], "follow_ups": [], "recurring": [], "interrupted": []}
    q["reminders"].append({
        "id": f"rem-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created": datetime.now().isoformat(),
        "created_by": "dispatch",
        "what": title,
        "when": desc,  # dispatcher skickar tid i description
        "channels": ["telegram", "session"],
        "status": "pending",
        "context": f"Dispatched task: {title}",
    })
    tmp = queue_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(q, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    import os as _os
    _os.replace(str(tmp), str(queue_path))
    return {"success": True, "summary": f"Reminder skapad: {title}"}


EXECUTORS = {"larry": executor_larry,
             "harry": executor_harry,
             "barry": executor_barry,
             "parry": executor_parry,
             "tarry": executor_tarry}


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
        }, indent=2, sort_keys=True), encoding="utf-8")
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

        # Expired pending tasks (older than their validity window, default
        # 48h) are moved to failed/ before listing -- a task that missed its
        # window should never run late, just show up as "expired" in failed/.
        try:
            task_lib.sweep_expired_pending(agent)
        except Exception as e:
            log.error(f"sweep_expired_pending error: {e}", exc_info=True)

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
