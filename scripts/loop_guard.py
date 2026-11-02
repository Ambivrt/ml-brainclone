"""loop_guard.py -- stops a session that runs the same tool call in circles.

Borrowed from Hermes Agent 0.22 ("unattended sessions hard-stop tool loops;
5 identical replays halt any tool"), tightened on one point: a call only
counts as a loop when both the call AND its response are identical. The same
`git status` after a change returns a new response and is not a lap. The
fifth identical Grep with the same empty response is.

Two thresholds per call (tool + input, per subagent):
  SAME_RESULT_LIMIT  identical responses in a row -> the next identical call is blocked
  TOTAL_LIMIT        same call in total, whatever the response -> blocked

A new Edit/Write (a change the session has not made before) resets
everything: the situation changed, re-running a test is no longer a lap.

The hook scripts/hooks/loop-guard.py calls record() after every tool and
check() before. Headless, the blocked call is denied; interactively the agent
is warned and the owner decides. denials(session) is read by the outcome
parser of the headless runner so a receipt shows that the loop stop fired.

State: one small JSON file per session plus an events.jsonl log, under
LARRY_LOOP_GUARD_DIR, else $LARRY_STATE_DIR/loop-guard, else
$VAULT_PATH/data/loop-guard.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

STATE_DIR_ENV = "LARRY_LOOP_GUARD_DIR"
HEADLESS_ENV = "LARRY_HEADLESS"
SAME_RESULT_LIMIT = 4
TOTAL_LIMIT = 10
MAX_CALLS = 400
STATE_TTL_SECONDS = 7 * 24 * 3600

# These wait and poll by definition; a repeated call is the job.
EXEMPT = {
    "ScheduleWakeup", "Monitor", "TaskOutput", "TaskStop", "ReadNotifications",
    "mcp__mempalace__mempalace_event_wait", "mcp__mempalace__mempalace_event_list",
    "mcp__mempalace__mempalace_status",
}
MUTATING = {"Edit", "Write", "NotebookEdit"}


def _state_dir() -> Path:
    env = os.environ.get(STATE_DIR_ENV)
    if env:
        return Path(env)
    base = os.environ.get("LARRY_STATE_DIR")
    if base:
        return Path(base) / "loop-guard"
    return Path(os.environ.get("VAULT_PATH", ".")) / "data" / "loop-guard"


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:80] or "unknown"
    return _state_dir() / f"{safe}.json"


def _empty() -> dict:
    return {"calls": {}, "blocked": {}, "denials": 0}


def load(session_id: str) -> dict:
    try:
        state = json.loads(_state_path(session_id).read_text(encoding="utf-8"))
        return {**_empty(), **state}
    except (OSError, ValueError):
        return _empty()


def _save(session_id: str, state: dict) -> None:
    p = _state_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _digest(obj) -> str:
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()[:16]


def call_key(tool: str, tool_input, agent_id: str = "") -> str:
    return _digest({"t": tool, "i": tool_input, "a": agent_id or ""})


def _label(tool: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for k in ("command", "pattern", "query", "file_path", "url", "prompt"):
            if tool_input.get(k):
                return f"{tool} {str(tool_input[k])[:80]}"
    return tool


def record(session_id: str, tool: str, tool_input, response, agent_id: str = "") -> str | None:
    """Note a finished call. Returns the reason when the call was just blocked."""
    if not session_id or tool in EXEMPT:
        return None
    state = load(session_id)
    key = call_key(tool, tool_input, agent_id)
    if tool in MUTATING and key not in state["calls"]:
        state["calls"], state["blocked"] = {}, {}
    calls = state["calls"]
    c = calls.pop(key, None) or {"n": 0, "same": 0, "res": None}
    res = _digest(response)
    c["n"] += 1
    c["same"] = c["same"] + 1 if c["res"] == res else 1
    c["res"] = res
    calls[key] = c  # last in order, oldest is trimmed first
    while len(calls) > MAX_CALLS:
        calls.pop(next(iter(calls)))
    reason = None
    if key not in state["blocked"]:
        if c["same"] >= SAME_RESULT_LIMIT:
            reason = f"{_label(tool, tool_input)} returned the same response {c['same']} times in a row"
        elif c["n"] >= TOTAL_LIMIT:
            reason = f"{_label(tool, tool_input)} ran {c['n']} times without the situation changing"
        if reason:
            state["blocked"][key] = reason
    _save(session_id, state)
    if reason:
        _log(session_id, "blocked", reason)
        _sweep()
    return reason


def check(session_id: str, tool: str, tool_input, agent_id: str = "") -> str | None:
    """The reason if the call is blocked in this session, else None."""
    if not session_id or tool in EXEMPT:
        return None
    return load(session_id)["blocked"].get(call_key(tool, tool_input, agent_id))


def note_denied(session_id: str, reason: str) -> None:
    state = load(session_id)
    state["denials"] = int(state.get("denials") or 0) + 1
    _save(session_id, state)
    _log(session_id, "denied", reason)


def denials(session_id: str) -> int:
    return int(load(session_id).get("denials") or 0) if session_id else 0


def _log(session_id: str, event: str, reason: str) -> None:
    try:
        row = {"at": datetime.now().isoformat(timespec="seconds"), "session": session_id,
               "event": event, "headless": os.environ.get(HEADLESS_ENV) == "1", "reason": reason}
        f = _state_dir() / "events.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _sweep() -> None:
    cutoff = time.time() - STATE_TTL_SECONDS
    try:
        for f in _state_dir().glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass
