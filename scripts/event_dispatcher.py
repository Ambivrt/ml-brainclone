"""event_dispatcher — subscribe to brains-bus, dispatch tasks on events.

A daemon that listens to the brains-bus as brain "dispatcher". For every
incoming event it runs a rule registry that decides whether a new task should
be created via task_lib.create_task.

Rules (easy to extend):

  • task-result(success=False)      → larry diagnoses the failure
  • session-error                    → larry triages the error
  • proactive-trigger                → dispatch directly to the agent
                                       specified in the payload:
                                       {agent, title, description, reason,
                                        dedup}

Anti-spam:
  • Per-rule dedup key with 1h TTL in RAM (lost on restart, OK).
  • Circuit breaker: cap at 20 dispatches per hour.

Guardian-friendly: heartbeat + PID file, clean SIGTERM shutdown. Your
supervisor (systemd, a Python guardian, scheduled task) restarts it when the
heartbeat goes stale.

ENV:
  VAULT_ROOT               — vault root (required)
  BRAINS_BUS_DIR           — dir containing bus_client.py / brains_bus.py
  DISPATCHER_NOTIF_DIR     — where to write heartbeat/pid/log
                             (default: VAULT_ROOT/.notifications)
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import task_lib  # noqa: E402


def _vault_root() -> Path:
    r = os.environ.get("VAULT_ROOT")
    if not r:
        raise SystemExit("VAULT_ROOT env var is required")
    return Path(r)


BUS_DIR = Path(os.environ.get("BRAINS_BUS_DIR", ""))
if not BUS_DIR or not BUS_DIR.exists():
    raise SystemExit("BRAINS_BUS_DIR env var is required and must exist")

sys.path.insert(0, str(BUS_DIR))
import bus_client  # noqa: E402  pyright: ignore[reportMissingImports]
import brains_bus as bus  # noqa: E402  pyright: ignore[reportMissingImports]

NOTIF_DIR = Path(os.environ.get(
    "DISPATCHER_NOTIF_DIR",
    _vault_root() / ".notifications"))

BRAIN = "dispatcher"
POLL_SECONDS = 2.0
HEARTBEAT_EVERY = 15
DEDUP_TTL = 60 * 60
RATE_CAP_PER_HOUR = 20

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("dispatcher")

_running = True
_dedup: dict[str, float] = {}
_dispatch_log: deque[float] = deque()


def _signal_stop(sig, frame):
    global _running
    log.info(f"signal {sig} — stopping.")
    _running = False


def _heartbeat(path: Path, state: str = "idle"):
    try:
        path.write_text(json.dumps({
            "pid": os.getpid(), "brain": BRAIN,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "state": state,
        }, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _dedup_allows(key: str) -> bool:
    now = time.time()
    for k in [k for k, t in _dedup.items() if now - t > DEDUP_TTL]:
        _dedup.pop(k, None)
    if key in _dedup:
        return False
    _dedup[key] = now
    return True


def _rate_allows() -> bool:
    now = time.time()
    while _dispatch_log and now - _dispatch_log[0] > 3600:
        _dispatch_log.popleft()
    return len(_dispatch_log) < RATE_CAP_PER_HOUR


def _dispatch(agent, title, desc, source, dedup_key):
    if not _dedup_allows(dedup_key):
        log.info(f"dedup-skip: {dedup_key}")
        return False
    if not _rate_allows():
        log.warning(f"rate cap reached — skipping {title}")
        return False
    try:
        path = task_lib.create_task(agent, title, desc,
                                    from_source=source, priority="normal")
        _dispatch_log.append(time.time())
        log.info(f"dispatched {agent}: {title} → {path.name}")
        return True
    except Exception as e:
        log.error(f"dispatch failed: {e}")
        return False


# ── Rules ────────────────────────────────────────────────────────────────────


def _rule_task_result_failed(ev):
    if ev.get("kind") != "task-result":
        return
    payload = ev.get("payload") or {}
    if payload.get("success") is not False:
        return
    agent = payload.get("agent", "?")
    task_id = payload.get("task_id", "?")
    title_src = payload.get("title", "(unknown)")
    err = payload.get("error") or payload.get("summary") or "unknown error"

    title = f"Diagnose failed {agent} task: {title_src[:40]}"
    desc = (f"Task {task_id} on {agent} failed.\n\n"
            f"**Title:** {title_src}\n**Error:** {err}\n\n"
            f"Open the full file in `_tasks/{agent}/failed/` and find the "
            f"root cause. Retry if transient, patch if systemic.")
    _dispatch("larry", title, desc,
              "dispatcher-task-failed", f"task-failed:{task_id}")


def _rule_session_error(ev):
    if ev.get("kind") != "session-error":
        return
    payload = ev.get("payload") or {}
    session_id = payload.get("session_id", "?")
    err = payload.get("error", "unknown")
    brain = ev.get("from_brain", "?")

    title = f"Triage {brain} session-error"
    desc = (f"{brain} crashed in session {session_id}.\n\n"
            f"**Error:** {err}\n\nCheck logs in notifications/; identify "
            f"whether the watchdog restarted cleanly or whether a patch is "
            f"needed.")
    _dispatch("larry", title, desc,
              "dispatcher-session-error",
              f"session-error:{brain}:{session_id}")


def _rule_proactive_trigger(ev):
    """Generic trigger: other scripts can post this to ask dispatcher to act.

    payload = {
        "agent":       "barry" | "harry" | "larry" | "parry",
        "title":       "...",
        "description": "...",
        "reason":      "why this is being triggered",
        "dedup":       "unique-key-for-dedup-window"
    }
    """
    if ev.get("kind") != "proactive-trigger":
        return
    p = ev.get("payload") or {}
    agent = p.get("agent")
    title = p.get("title")
    desc = p.get("description", "")
    reason = p.get("reason", "")
    dedup = p.get("dedup") or f"proactive:{agent}:{title}"

    if agent not in ("larry", "harry", "barry", "parry", "tarry"):
        log.warning(f"proactive-trigger: invalid agent {agent}")
        return
    if not title:
        return

    full_desc = desc
    if reason:
        full_desc = f"{desc}\n\n**Reason:** {reason}" if desc else f"Reason: {reason}"
    _dispatch(agent, title, full_desc,
              "dispatcher-proactive-trigger", dedup)


RULES = [_rule_task_result_failed, _rule_session_error, _rule_proactive_trigger]


# ── Main ─────────────────────────────────────────────────────────────────────


def run():
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    hb_path = NOTIF_DIR / "event-dispatcher.heartbeat"
    pid_path = NOTIF_DIR / "event-dispatcher.pid"
    log_path = NOTIF_DIR / "event-dispatcher.log"

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
    signal.signal(signal.SIGINT, _signal_stop)
    signal.signal(signal.SIGTERM, _signal_stop)

    bus.init()
    os.environ["BRAIN_NAME"] = BRAIN
    log.info(f"event-dispatcher online (pid={os.getpid()}, brain={BRAIN})")
    _heartbeat(hb_path, "idle")

    last_hb = 0.0
    while _running:
        now = time.time()
        if now - last_hb > HEARTBEAT_EVERY:
            _heartbeat(hb_path, "idle")
            last_hb = now

        try:
            events = bus.read_inbox(BRAIN, limit=50)
        except Exception as e:
            log.error(f"read_inbox error: {e}")
            events = []

        for ev in events:
            if not _running:
                break
            try:
                _heartbeat(hb_path, "processing")
                for rule in RULES:
                    rule(ev)
            except Exception as e:
                log.error(f"rule error on event {ev.get('id')}: {e}",
                          exc_info=True)
            finally:
                _heartbeat(hb_path, "idle")

        time.sleep(POLL_SECONDS)

    log.info("event-dispatcher stopped.")


if __name__ == "__main__":
    run()
