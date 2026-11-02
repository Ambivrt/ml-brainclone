"""extern-taint-read.py -- PostToolUse hook for tools that fetch outside text.

Notes that the session read something somebody else wrote
(scripts/extern_taint.py), so the oversight gate can weigh it before an
outward action. Silent, always exit 0: a read is never blocked.

Wire it under PostToolUse with matcher "*" (the module decides which tool
calls count). The module is found next to the hook (scripts/), in
LARRY_SCRIPTS_DIR, or in $VAULT_PATH/scripts.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _add_module_path() -> None:
    here = Path(__file__).resolve()
    candidates = [os.environ.get("LARRY_SCRIPTS_DIR"), here.parents[1], here.parent,
                  Path(os.environ.get("VAULT_PATH", ".")) / "scripts"]
    for c in candidates:
        if c and (Path(c) / "extern_taint.py").is_file():
            sys.path.insert(0, str(c))
            return


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        payload = json.loads(sys.stdin.read())
        _add_module_path()
        import extern_taint

        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return 0
        source = extern_taint.tool_source(str(payload.get("tool_name") or ""),
                                          payload.get("tool_input"))
        if source:
            extern_taint.record(session_id, source)
    except Exception:  # noqa: BLE001 -- the hook must never disturb a read
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
