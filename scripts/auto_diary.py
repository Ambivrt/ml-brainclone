"""auto_diary — automatic session diary entry on session end.

Called as a Claude Code hook (PostToolUse:Stop) or manually. Summarises
session activity from git diff and writes to the semantic memory system.

If the memory server is unreachable, entries are buffered to a local
JSONL file for later replay.

Hook registration (in .claude/settings.json):
    "PostToolUse": [{
        "matcher": "Stop",
        "hooks": [{
            "type": "command",
            "command": "python path/to/auto_diary.py --auto"
        }]
    }]

ENV:
    VAULT_ROOT        — vault root (defaults to ~/vault if unset)
    MEMORY_MCP_URL    — URL of the memory MCP server (default: http://localhost:8766/mcp)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "vault"))
MEMORY_URL = os.environ.get("MEMORY_MCP_URL", "http://localhost:8766/mcp")
FALLBACK_PATH = VAULT_ROOT / "_private" / "diary-pending.jsonl"
# Errors log: the actual exception (type, message, timing, attempt number)
# rather than just "failed", so a stuck backlog can be diagnosed without
# reproducing it. Lives next to the fallback queue.
ERROR_LOG_PATH = VAULT_ROOT / "_private" / "diary-write-errors.log"

# A hook does not get the whole session's budget, but a request timeout that
# is too short trips exactly on the slow tail of a loaded memory server —
# "the server actually wrote it, the client just gave up". A short second
# attempt covers the genuinely transient part of that failure (queueing, a
# brief lock wait) without doubling the cost of every call.
MEMORY_TIMEOUT_S = 10
MEMORY_RETRY_TIMEOUT_S = 5
MEMORY_RETRY_DELAY_S = 2.0


def _get_session_activity() -> str:
    """Gather session activity from git status."""
    parts = []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", cwd=str(VAULT_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            files = result.stdout.strip().split("\n")
            parts.append(f"{len(files)} changed files")
            categories: dict[str, int] = {}
            for f in files:
                top = f.split("/")[0] if "/" in f else "root"
                categories[top] = categories.get(top, 0) + 1
            for cat, count in sorted(categories.items(),
                                      key=lambda x: -x[1])[:5]:
                parts.append(f"  {cat}: {count}")
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", cwd=str(VAULT_ROOT),
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            new_files = [ln for ln in lines if ln.startswith("??")]
            modified = [ln for ln in lines
                        if ln.startswith(" M") or ln.startswith("M ")]
            if new_files:
                parts.append(f"{len(new_files)} new files")
            if modified:
                parts.append(f"{len(modified)} modified")
    except Exception:
        pass

    return "\n".join(parts) if parts else "minimal activity"


def _build_entry(activity: str) -> str:
    """Build a compressed diary entry from activity."""
    now = datetime.now()
    topics = []
    lower = activity.lower()
    for keyword in ("image", "audio", "voice", "gatekeeper", "schedule",
                    "translate", "memory", "work", "project"):
        if keyword in lower:
            topics.append(keyword)
    if not topics:
        topics.append("vault-work")

    return (f"SESSION:{now.strftime('%Y-%m-%d')}T{now.strftime('%H:%M')}"
            f"|session|{'+'.join(topics)}|auto-diary")


def _log_write_failure(entry: str, err: Exception, elapsed: float, timeout: float,
                        attempt: int) -> None:
    """Append the actual error to a log file. Must never raise, a broken
    log must never block the fallback write."""
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().isoformat(timespec='seconds')} "
                f"attempt={attempt} {type(err).__name__}: {err} "
                f"(took {elapsed:.1f}s, timeout {timeout:.0f}s) "
                f"entry={entry[:120]!r}\n"
            )
    except OSError:
        pass


def _send_once(entry: str, timeout: float) -> tuple[bool, float, Exception | None]:
    """One request to the memory MCP server. Returns (ok, elapsed, error)."""
    t0 = time.monotonic()
    try:
        import urllib.request
        body = json.dumps({
            "tool": "mempalace_diary_write",
            "params": {"agent_name": "text-mode", "entry": entry},
        }).encode()
        req = urllib.request.Request(
            MEMORY_URL, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            return True, time.monotonic() - t0, None
    except Exception as e:
        return False, time.monotonic() - t0, e


def write_diary(entry: str | None = None) -> bool:
    """Write diary entry to memory via MCP HTTP.

    One attempt, and if it fails with a network/timeout error (not a server
    error, the server answered and said no, a retry changes nothing): one
    more attempt with a shorter timeout. If both fail, the entry falls back
    to the pending queue with a `reason` field, so the cause is visible
    without digging through logs."""
    if not entry:
        activity = _get_session_activity()
        entry = _build_entry(activity)

    ok, elapsed, err = _send_once(entry, MEMORY_TIMEOUT_S)
    if ok:
        print(f"Diary written: {entry}")
        return True

    print(f"Diary write failed (attempt 1, {type(err).__name__}: {err})")
    _log_write_failure(entry, err, elapsed, MEMORY_TIMEOUT_S, attempt=1)

    if isinstance(err, RuntimeError):
        # The server answered and rejected the write, retrying with the
        # same content changes nothing, only network/timeout errors are
        # worth a second try.
        _write_fallback(entry, reason=f"server error: {err}")
        return False

    time.sleep(MEMORY_RETRY_DELAY_S)
    ok2, elapsed2, err2 = _send_once(entry, MEMORY_RETRY_TIMEOUT_S)
    if ok2:
        print(f"Diary written (attempt 2): {entry}")
        return True

    print(f"Diary write failed (attempt 2, {type(err2).__name__}: {err2})")
    _log_write_failure(entry, err2, elapsed2, MEMORY_RETRY_TIMEOUT_S, attempt=2)

    reason = (
        f"attempt 1: {type(err).__name__}: {err} ({elapsed:.1f}s, timeout {MEMORY_TIMEOUT_S}s); "
        f"attempt 2: {type(err2).__name__}: {err2} ({elapsed2:.1f}s, timeout {MEMORY_RETRY_TIMEOUT_S}s)"
    )
    _write_fallback(entry, reason=reason)
    return False


def _write_fallback(entry: str, reason: str | None = None) -> None:
    """Save to local JSONL when the memory server is unavailable."""
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "agent": "text-mode",
        "entry": entry,
        "ts": datetime.now().isoformat(),
        "status": "pending",
    }
    if reason:
        row["reason"] = reason
    with open(FALLBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Diary buffered: {FALLBACK_PATH}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("entry", nargs="?", default=None)
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    if args.auto or not args.entry:
        write_diary()
    else:
        write_diary(args.entry)
