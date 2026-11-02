"""skill-usage.py -- PostToolUse (Skill|Read): logs used skills (scripts/skill_usage.py).

A Read of anything that does not sit in a skills directory is dropped before
the module loads, so the hook costs one JSON parse on ordinary reads. Always
exit 0, never any output.

Wire it under PostToolUse with matcher "Skill|Read". The module is found
next to the hook (scripts/), in LARRY_SCRIPTS_DIR, or in $VAULT_PATH/scripts.
"""
import json
import os
import sys
from pathlib import Path

try:
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


def _add_module_path() -> None:
    here = Path(__file__).resolve()
    candidates = [os.environ.get("LARRY_SCRIPTS_DIR"), here.parents[1], here.parent,
                  Path(os.environ.get("VAULT_PATH", ".")) / "scripts"]
    for c in candidates:
        if c and (Path(c) / "skill_usage.py").is_file():
            sys.path.insert(0, str(c))
            return


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, TypeError):
        return
    if payload.get("tool_name") == "Read":
        fp = str((payload.get("tool_input") or {}).get("file_path") or "").replace("\\", "/").lower()
        if "/skills/" not in fp:
            return
    _add_module_path()
    import skill_usage
    skill_usage.record(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
