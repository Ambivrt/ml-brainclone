"""loop-guard.py -- PreToolUse + PostToolUse(+Failure): stops tool loops (scripts/loop_guard.py).

Post: records the call and its response. When a call has just gone into a
loop, the agent is told via additionalContext. Pre: headless, a blocked call
is denied, because nobody is there to break the lap. Interactively it is let
through; the warning is enough and the owner sees what happens.

An error here must never stop a tool: everything except the denial itself is
swallowed.

Wire it in .claude/settings.json under PreToolUse, PostToolUse and
PostToolUseFailure with matcher "*". The modules are found next to the hook
(scripts/), in LARRY_SCRIPTS_DIR, or in $VAULT_PATH/scripts.
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
        if c and (Path(c) / "loop_guard.py").is_file():
            sys.path.insert(0, str(c))
            return


def _out(event: str, **fields) -> None:
    json.dump({"hookSpecificOutput": {"hookEventName": event, **fields}}, sys.stdout, ensure_ascii=False)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, TypeError):
        return
    event = payload.get("hook_event_name", "")
    session_id = str(payload.get("session_id") or "")
    tool = str(payload.get("tool_name") or "")
    if not session_id or not tool:
        return
    _add_module_path()
    try:
        import loop_guard
    except Exception:
        return
    tool_input = payload.get("tool_input")
    agent_id = str(payload.get("agent_id") or "")
    headless = os.environ.get("LARRY_HEADLESS") == "1"

    if event == "PreToolUse":
        if not headless:
            return
        reason = loop_guard.check(session_id, tool, tool_input, agent_id)
        if reason:
            loop_guard.note_denied(session_id, reason)
            _out("PreToolUse", permissionDecision="deny",
                 permissionDecisionReason=f"LOOP STOP: {reason}. The same call gives the same result again. "
                                          f"Change approach, or finish with TASK-FAILED and the reason.")
        return

    # Failed calls arrive as PostToolUseFailure with the error instead of the
    # response. The same Edit failing the same way over and over is the most
    # common loop.
    if event in ("PostToolUse", "PostToolUseFailure"):
        if event == "PostToolUseFailure":
            response = {"error": payload.get("error", "")}
        else:
            response = payload.get("tool_response", payload.get("tool_result", ""))
        reason = loop_guard.record(session_id, tool, tool_input, response, agent_id)
        if reason:
            next_step = ("The next identical call is denied." if headless
                         else "Change approach or ask the owner what is missing.")
            _out(event, additionalContext=f"LOOP: {reason}. {next_step}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
