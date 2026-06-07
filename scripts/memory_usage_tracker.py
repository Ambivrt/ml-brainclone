"""memory_usage_tracker.py -- PostToolUse hook that logs memory file reads.

Part 1 of usage-driven memory curation ("dreaming", see docs/memory-system.md).

Receives Claude Code's hook JSON on stdin. If the Read call targets a file
under the auto-memory directory, appends a JSONL line to .usage/usage.jsonl.
The log is consumed nightly by memory_usage_curate.py.

Contract: ALWAYS exit 0, never output (hooks must not disturb the session),
stdlib only, fast. Errors are swallowed -- a broken log must never block Read.

Wire it in .claude/settings.json:
  "PostToolUse": [
    {"matcher": "Read",
     "hooks": [{"type": "command",
                "command": "python /path/to/scripts/memory_usage_tracker.py"}]}
  ]

Configure via env:
  MEMORY_DIR  -- auto-memory directory (default: ./memory)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

MEMORY_ROOT = Path(os.environ.get("MEMORY_DIR", "./memory"))
USAGE_LOG = MEMORY_ROOT / ".usage" / "usage.jsonl"

# Loaded by the harness at session start, not active recall -- not logged
IGNORE_NAMES = {"MEMORY.md", "USER.md"}


def extract_event(payload: dict) -> dict | None:
    """Hook JSON -> log line, or None if the call is not a memory-file read."""
    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path:
        return None
    try:
        rel = Path(file_path).resolve().relative_to(MEMORY_ROOT.resolve())
    except (ValueError, OSError):
        return None
    if rel.parts and rel.parts[0] == ".usage":
        return None
    if rel.name in IGNORE_NAMES or rel.suffix.lower() != ".md":
        return None
    return {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "session": payload.get("session_id", ""),
        "file": rel.as_posix(),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        event = extract_event(payload)
        if event:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never block the session
    return 0


if __name__ == "__main__":
    sys.exit(main())
