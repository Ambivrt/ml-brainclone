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
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "vault"))
MEMORY_URL = os.environ.get("MEMORY_MCP_URL", "http://localhost:8766/mcp")
FALLBACK_PATH = VAULT_ROOT / "_private" / "diary-pending.jsonl"


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


def write_diary(entry: str | None = None) -> bool:
    """Write diary entry to memory via MCP HTTP. Falls back to local JSONL."""
    if not entry:
        activity = _get_session_activity()
        entry = _build_entry(activity)

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
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("success") or result.get("entry_id"):
                print(f"Diary written: {entry}")
                return True
            print(f"Diary result: {result}")
            return True
    except Exception as e:
        print(f"Diary write failed (memory server offline?): {e}")
        _write_fallback(entry)
        return False


def _write_fallback(entry: str) -> None:
    """Save to local JSONL when the memory server is unavailable."""
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FALLBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "agent": "text-mode",
            "entry": entry,
            "ts": datetime.now().isoformat(),
            "status": "pending",
        }) + "\n")
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
