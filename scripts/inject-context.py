"""inject-context.py -- Pre-turn context injection hook.

Designed to run as a Claude Code PreToolUse hook. Injects fresh bus events
and fired reminders into the conversation via stderr, so the agent sees
them mid-session without having to ask.

Throttled: runs at most once per THROTTLE_S seconds. All other invocations
exit immediately after a timestamp check (~0ms overhead).

Configure via environment variables:
    VAULT_ROOT      -- vault directory (required)
    BUS_DB_PATH     -- path to brains-bus SQLite DB (default: VAULT_ROOT/_private/brains-bus.db)
    REMINDER_QUEUE  -- path to reminder queue JSON (default: VAULT_ROOT/_private/tarry-queue.json)
    INJECT_THROTTLE -- seconds between injections (default: 90)
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", "."))
BUS_DB = Path(os.environ.get("BUS_DB_PATH", str(VAULT / "_private" / "brains-bus.db")))
REMINDER_Q = Path(os.environ.get("REMINDER_QUEUE", str(VAULT / "_private" / "tarry-queue.json")))
STATE_FILE = VAULT / "_private" / ".inject-context-state.json"
THROTTLE_S = int(os.environ.get("INJECT_THROTTLE", "90"))


def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_ts": 0, "last_event_id": 0}


def _save_state(state):
    STATE_FILE.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


def _get_bus_events(since_id):
    if not BUS_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(BUS_DB), timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ts, from_brain, to_brain, kind, parry_verdict "
            "FROM events WHERE id > ? ORDER BY id DESC LIMIT 5",
            (since_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def _get_fired_reminders(since_ts):
    if not REMINDER_Q.exists():
        return []
    try:
        q = json.loads(REMINDER_Q.read_text(encoding="utf-8"))
        fired = []
        for r in q.get("reminders", []):
            if r.get("status") == "fired":
                ft = r.get("fired_at", "")
                if ft and ft > since_ts:
                    fired.append(r)
        return fired[:3]
    except Exception:
        return []


def main():
    state = _load_state()
    now = time.time()

    if now - state["last_ts"] < THROTTLE_S:
        return

    events = _get_bus_events(state.get("last_event_id", 0))
    last_check_iso = (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state["last_ts"]))
        if state["last_ts"]
        else ""
    )
    reminders = _get_fired_reminders(last_check_iso)

    new_state = {
        "last_ts": now,
        "last_event_id": events[-1]["id"] if events else state.get("last_event_id", 0),
    }
    _save_state(new_state)

    if not events and not reminders:
        return

    lines = []
    if events:
        lines.append("BUS-UPDATE:")
        for e in events:
            v = f" [{e['parry_verdict']}]" if e.get("parry_verdict") else ""
            lines.append(
                f"  #{e['id']} {e['from_brain']}->{e['to_brain'] or '*'} {e['kind']}{v}"
            )
    if reminders:
        lines.append("REMINDERS-FIRED:")
        for r in reminders:
            lines.append(f"  {r.get('id', '?')}: {r.get('message', '')[:120]}")

    sys.stderr.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
