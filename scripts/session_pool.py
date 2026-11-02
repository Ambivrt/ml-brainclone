"""session_pool -- Persistent CLI sessions per agent.

Maintains session IDs so --resume can skip CLI boot overhead.
Sessions auto-expire after MAX_AGE_S inactivity or MAX_FAILURES consecutive errors.

Inspired by Pi.dev's RPC mode: keep context, skip cold starts.

A tainted session is not pooled. If it has read untrusted external text
(extern_taint) or private level 3-4 content (privacy_taint, if present), that stays
in its context, and the next task would inherit both the text and the mark. The
session may finish its task, then the next task starts cold and clean.

Configure:
    SESSION_POOL_DIR  -- where to store session state (default: VAULT_ROOT/_private)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("session-pool")

MAX_AGE_S = int(os.environ.get("SESSION_POOL_MAX_AGE", "3600"))
MAX_FAILURES = int(os.environ.get("SESSION_POOL_MAX_FAILURES", "3"))


def _state_dir() -> Path:
    custom = os.environ.get("SESSION_POOL_DIR")
    if custom:
        return Path(custom)
    vault = os.environ.get("VAULT_ROOT", ".")
    return Path(vault) / "_private"


def _state_path(agent: str) -> Path:
    return _state_dir() / f"task-session-{agent}.json"


def _load(agent: str) -> dict:
    p = _state_path(agent)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("last_used", 0) > MAX_AGE_S:
            log.info(f"[{agent}] session expired ({MAX_AGE_S}s)")
            return {}
        return data
    except Exception:
        return {}


def _save(agent: str, data: dict):
    _state_path(agent).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def taint_reason(session_id: str) -> str | None:
    """Why the session must not be reused, or None if it is clean."""
    if not session_id:
        return None
    try:
        import extern_taint
        if extern_taint.tainted(session_id):
            return "read untrusted external text"
    except Exception as e:  # noqa: BLE001 -- the pool must work without the taint modules
        log.warning(f"extern taint check did not answer: {e}")
    try:
        import privacy_taint  # optional: only present when level tracking is set up
    except ImportError:
        return None
    try:
        level = int(privacy_taint.load(session_id).get("max", 0))
        if level >= privacy_taint.PRIVATE_FLOOR:
            return f"read level {level} content"
    except Exception as e:  # noqa: BLE001
        log.warning(f"privacy taint check did not answer: {e}")
    return None


def get_session_id(agent: str) -> str | None:
    """Return the stored session ID, or None if no valid session exists."""
    data = _load(agent)
    session_id = data.get("session_id")
    reason = taint_reason(session_id)
    if reason:
        log.info(f"[{agent}] session {session_id[:8]} {reason}, starting cold")
        clear_session(agent)
        return None
    return session_id


def update_session(agent: str, session_id: str, success: bool):
    """Update the session after a task execution."""
    data = _load(agent)
    reason = taint_reason(session_id)
    if reason:
        log.info(f"[{agent}] session {session_id[:8]} {reason}, not pooled")
        clear_session(agent)
        return
    if success:
        data["session_id"] = session_id
        data["last_used"] = time.time()
        data["consecutive_failures"] = 0
    else:
        fails = data.get("consecutive_failures", 0) + 1
        if fails >= MAX_FAILURES:
            log.warning(f"[{agent}] {fails} failures, clearing session")
            data = {}
        else:
            data["consecutive_failures"] = fails
            data["last_used"] = time.time()
    _save(agent, data)


def clear_session(agent: str):
    """Remove a session entirely (e.g., after an invalid session error)."""
    p = _state_path(agent)
    if p.exists():
        p.unlink(missing_ok=True)
    log.info(f"[{agent}] session cleared")
