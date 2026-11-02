"""
Token hygiene checker — run weekly to detect context bloat.

Checks CLAUDE.md size, MEMORY.md line count, and active plugin count.
Flags only when thresholds are exceeded.

Usage:
    python scripts/token_hygiene_check.py
    python scripts/token_hygiene_check.py --vault /path/to/vault --memory /path/to/MEMORY.md

Configure thresholds below or override via environment variables:
    TOKEN_HYGIENE_CLAUDE_WORDS=2500
    TOKEN_HYGIENE_MEMORY_LINES=150
    TOKEN_HYGIENE_MAX_PLUGINS=5
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

VAULT = Path(os.environ.get("VAULT_ROOT", "."))
CLAUDE_MD = VAULT / "CLAUDE.md"

MEMORY_CANDIDATES = [
    Path(os.environ.get("MEMORY_MD", "")) if os.environ.get("MEMORY_MD") else None,
    Path.home() / ".claude" / "projects" / "memory" / "MEMORY.md",
    VAULT / ".claude" / "memory" / "MEMORY.md",
]

USER_SETTINGS = Path.home() / ".claude" / "settings.json"

THRESHOLDS = {
    # CLAUDE.md is not slimmed on purpose. The threshold guards against
    # uncontrolled growth, not against size itself.
    "claude_md_words": int(os.environ.get("TOKEN_HYGIENE_CLAUDE_WORDS", 2500)),
    "memory_md_lines": int(os.environ.get("TOKEN_HYGIENE_MEMORY_LINES", 150)),
    "active_plugins": int(os.environ.get("TOKEN_HYGIENE_MAX_PLUGINS", 5)),
}


def find_memory_md():
    for p in MEMORY_CANDIDATES:
        if p and p.exists():
            return p
    return None


def check_claude_md():
    if not CLAUDE_MD.exists():
        return {"ok": True, "msg": "CLAUDE.md not found (skipped)"}
    text = CLAUDE_MD.read_text(encoding="utf-8")
    words = len(text.split())
    over = words > THRESHOLDS["claude_md_words"]
    return {
        "ok": not over,
        "words": words,
        "threshold": THRESHOLDS["claude_md_words"],
        "msg": f"CLAUDE.md: {words} words (max {THRESHOLDS['claude_md_words']})"
        + (", review what has grown" if over else " OK"),
    }


def check_memory_md():
    path = find_memory_md()
    if not path:
        return {"ok": True, "msg": "MEMORY.md not found (skipped)"}
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    count = len(lines)
    over = count > THRESHOLDS["memory_md_lines"]
    return {
        "ok": not over,
        "lines": count,
        "threshold": THRESHOLDS["memory_md_lines"],
        "msg": f"MEMORY.md: {count} lines (max {THRESHOLDS['memory_md_lines']})"
        + (", review what has grown" if over else " OK"),
    }


def check_plugins():
    if not USER_SETTINGS.exists():
        return {"ok": True, "msg": "settings.json not found (skipped)"}
    try:
        settings = json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"ok": True, "msg": "settings.json unreadable (skipped)"}
    enabled = settings.get("enabledPlugins", {})
    active = [k for k, v in enabled.items() if v is True]
    count = len(active)
    over = count > THRESHOLDS["active_plugins"]
    return {
        "ok": not over,
        "active": count,
        "names": [n.split("@")[0] for n in active],
        "threshold": THRESHOLDS["active_plugins"],
        "msg": f"Plugins: {count} active (max {THRESHOLDS['active_plugins']})"
        + (" — DISABLE UNUSED" if over else " OK"),
    }


def run():
    results = {
        "ts": datetime.now().isoformat(),
        "claude_md": check_claude_md(),
        "memory_md": check_memory_md(),
        "plugins": check_plugins(),
    }

    checks = [results["claude_md"], results["memory_md"], results["plugins"]]
    all_ok = all(r["ok"] for r in checks)
    results["all_ok"] = all_ok

    flags = [r["msg"] for r in checks if not r["ok"]]
    results["summary"] = (
        "TOKEN HYGIENE: " + " | ".join(flags) if flags else "Token hygiene OK"
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run())
