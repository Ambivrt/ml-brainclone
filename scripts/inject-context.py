"""inject-context.py -- PreToolUse hook (Edit|Write): a voice hint for the file being written.

The hint goes out as hookSpecificOutput.additionalContext on stdout. Text on
stderr with exit code 0 never reaches the model, so every injection takes this
route. An earlier version wrote bus events and reminders to stderr on every
tool call; none of it was ever seen. Bus events are better watched with a
Monitor started at session init than pushed through a hook.

Voice rules apply to prose. Code and config get no hint.

Configure via environment variables:
    VAULT_ROOT       -- vault directory (required)
    VOICE_HINTS_PATH -- path to voice-profile-hints.json (default: VAULT_ROOT/.claude/hooks/voice-profile-hints.json)

voice-profile-hints.json:
    {"patterns": [{"match": ["linkedin", "post"], "hint": "..."}], "default_hint": "..."}
"""
import json
import os
import sys
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", "."))
VOICE_HINTS = Path(os.environ.get("VOICE_HINTS_PATH", str(VAULT / ".claude" / "hooks" / "voice-profile-hints.json")))
PROSE = (".md", ".txt")


def _get_voice_hint(file_path):
    if not VOICE_HINTS.exists():
        return None
    try:
        hints = json.loads(VOICE_HINTS.read_text(encoding="utf-8"))
    except Exception:
        return None
    fp_lower = file_path.lower().replace("\\", "/")
    for pattern in hints.get("patterns", []):
        for keyword in pattern.get("match", []):
            if keyword.lower() in fp_lower:
                return pattern["hint"]
    return hints.get("default_hint")


def voice_context(payload):
    """Hook output for an Edit/Write on a prose file, otherwise None."""
    if payload.get("tool_name") not in ("Edit", "Write"):
        return None
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path.lower().endswith(PROSE):
        return None
    hint = _get_voice_hint(file_path)
    if not hint:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": hint,
    }}


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return
    out = voice_context(payload)
    if out:
        json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    # A hook must never block the tool call: any failure exits 0 without output
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
