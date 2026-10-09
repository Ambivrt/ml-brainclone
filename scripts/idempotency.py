"""idempotency.py -- idempotency keys for side effects that leave the machine.

The task queue is at-least-once: if the receipt dies after the side effect
succeeded, the lease runs out, the job goes back and runs again. For local file
writes that is harmless. For mail, chat messages and paid API calls it is a
double charge. The key is stored BEFORE the call, so a rerun sees that the side
effect already started or finished and skips it.

Three states per key:

  pending  claim() done, outcome unknown. The process died between claim() and
           confirm(), or the call timed out. Nobody knows whether it went out.
           A rerun SKIPS (at-most-once): better one missing mail than two.
  done     confirm() done. A rerun skips.
  (none)   release() after a certain failure (the call never left). A rerun may
           try again.

Scope from the environment: the task watcher sets IDEMPOTENCY_SCOPE=<task_id>
and IDEMPOTENCY_ATTEMPT=<n> for the executor. scoped_key() then builds a key
from scope + channel + recipient + a sequence number within the attempt, so
the n-th send to the same recipient in attempt 2 collides with the n-th in
attempt 1. A sequence number rather than a content hash: a model rerunning a
job never phrases things the same way twice. The counter lives in the
database, because every send from an executor is its own Python process.

Without a scope (interactive session, standalone script) scoped_key() returns
None and the side effect runs as before.

    key = idempotency.scoped_key("mail", to)
    if key and not idempotency.claim(key, kind="mail"):
        return "skipped: already sent"
    ok = send(...)
    idempotency.confirm(key) if ok else idempotency.release(key)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("IDEMPOTENCY_DB", Path(os.environ.get("VAULT_PATH", ".")) / "data" / "idempotency.db"))


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    conn.execute("CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, state TEXT, kind TEXT, meta TEXT, at REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS seq (scope TEXT PRIMARY KEY, n INTEGER)")
    return conn


def scoped_key(channel: str, target: str) -> str | None:
    """A key for the next send on this channel to this target, or None without a scope."""
    scope = os.environ.get("IDEMPOTENCY_SCOPE")
    if not scope:
        return None
    attempt = os.environ.get("IDEMPOTENCY_ATTEMPT", "1")
    counter = f"{scope}|{attempt}|{channel}|{target.lower()}"
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT n FROM seq WHERE scope = ?", (counter,)).fetchone()
        n = (row[0] if row else 0) + 1
        conn.execute("INSERT OR REPLACE INTO seq (scope, n) VALUES (?, ?)", (counter, n))
        conn.execute("COMMIT")
    finally:
        conn.close()
    return f"{scope}|{channel}|{target.lower()}|{n}"


def claim(key: str, kind: str = "", meta: dict | None = None) -> bool:
    """True if this caller may run the side effect. False if it is pending or done."""
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM keys WHERE key = ?", (key,)).fetchone():
            conn.execute("ROLLBACK")
            return False
        conn.execute("INSERT INTO keys VALUES (?, 'pending', ?, ?, ?)",
                     (key, kind, json.dumps(meta or {}, ensure_ascii=False), time.time()))
        conn.execute("COMMIT")
        return True
    finally:
        conn.close()


def confirm(key: str) -> None:
    conn = _db()
    try:
        conn.execute("UPDATE keys SET state = 'done', at = ? WHERE key = ?", (time.time(), key))
    finally:
        conn.close()


def release(key: str) -> None:
    """Only after a certain failure. A timeout is not certain: leave it pending."""
    conn = _db()
    try:
        conn.execute("DELETE FROM keys WHERE key = ? AND state = 'pending'", (key,))
    finally:
        conn.close()
