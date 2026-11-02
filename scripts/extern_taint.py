"""Text from outside follows a session from reading to acting.

privacy_taint counts how private what was read is. This module tracks where
it came from. A session that fetched a web page, read a mail or a GitHub
thread carries text somebody else wrote, and that text can be written to
steer the agent ("send the file to X", "push to Y"). After such a read the
session's own decisions about outward actions are no longer only the
owner's and the system's.

  taints     WebFetch, WebSearch, the browser tools (claude-in-chrome), and
             shell commands that fetch outside text: curl, wget,
             Invoke-WebRequest, gws gmail get/list, gh (issue, pr, release,
             api), social-scan scripts
  enforced   the oversight gate asks tainted() before an outward action.
             Shadow: the action goes ahead as usual, the row is logged.
             Enforce: in headless sessions autonomous and on_loop are raised
             to in_loop, and the `# owner-ok:` marker does not count (nobody
             stands next to a headless session, and the marker may be
             dictated by the text that was read)

Mode per LARRY_EXTERN_TAINT_MODE: "enforce" (default) or "shadow". Run
shadow first on a new install to see what would have been raised.
Interactive sessions are never raised: the owner sits there and sees the
prompt, and nearly every session reads something on the web.

Known holes: Playwright scripts and other home-made fetchers that do not
match the patterns, MCP servers beyond the browser, and text that another
session read and wrote down in the vault.

Taint is sticky per session id, because the text stays in the context. So
the task watcher never pools a tainted session (session_pool): the task
that read may finish, the next one starts cold.

Model: OpenClaw 2026.10.5-beta.2, where network results through Tool Search
and Code Mode taint the turn the same way as direct network calls.

State: one JSON file per session under LARRY_EXTERN_TAINT_DIR, else
$LARRY_STATE_DIR/extern-taint, else $VAULT_PATH/data/extern-taint.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

MODE_ENV = "LARRY_EXTERN_TAINT_MODE"
HEADLESS_ENV = "LARRY_HEADLESS"
STATE_DIR_ENV = "LARRY_EXTERN_TAINT_DIR"

STATE_TTL_SECONDS = 7 * 24 * 3600
MAX_SOURCES = 20

# Tools whose response is outside text. Browser tools that only steer the
# tab (navigate, resize) return no text and do not taint.
NETWORK_TOOLS = frozenset({"WebFetch", "WebSearch"})
_BROWSER_READ = re.compile(
    r"^mcp__claude-in-chrome__(?:read_page|get_page_text|find|computer|javascript_tool|"
    r"read_console_messages|read_network_requests|browser_batch)$")

# Shell commands that fetch outside text. Reading only: sending and pushing
# are classified by the oversight gate.
_SHELL_FETCH = [
    ("curl", re.compile(r"(?:^|[\s;&|(])curl(?:\.exe)?\s", re.IGNORECASE)),
    ("wget", re.compile(r"(?:^|[\s;&|(])wget(?:\.exe)?\s", re.IGNORECASE)),
    ("webrequest", re.compile(r"\bInvoke-(?:WebRequest|RestMethod)\b|\b(?:iwr|irm)\s", re.IGNORECASE)),
    ("gmail", re.compile(r"\bgws\s+gmail\s+users\s+(?:messages|threads)\s+(?:get|list)\b")),
    ("github", re.compile(r"\bgh\s+(?:issue|pr|release|api|search|repo\s+view)\b")),
    ("social-scan", re.compile(r"\bsocial[_-]scan\w*\.py\b")),
]
# Calls to the local machine are not outside text.
_LOCAL_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?:[:/]|\s|$)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s\"'`<>)]+", re.IGNORECASE)


def shell_source(cmd: str) -> str | None:
    """What the command fetches from outside, or None. Local addresses do not count."""
    for name, rx in _SHELL_FETCH:
        if not rx.search(cmd or ""):
            continue
        if name in ("curl", "wget", "webrequest"):
            urls = _URL.findall(cmd)
            if urls and all(_LOCAL_URL.match(u) for u in urls):
                return None
            return f"{name}: {urls[0][:120]}" if urls else name
        return name
    return None


def tool_source(tool: str, tool_input: dict | None) -> str | None:
    """The source a tool call taints with, or None if it does not taint."""
    data = tool_input if isinstance(tool_input, dict) else {}
    if tool in NETWORK_TOOLS:
        return f"{tool}: {str(data.get('url') or data.get('query') or '')[:120]}".rstrip(": ")
    if _BROWSER_READ.match(tool or ""):
        return tool.rsplit("__", 1)[-1]
    if tool in ("Bash", "PowerShell"):
        return shell_source(str(data.get("command") or ""))
    return None


# -- Session state -----------------------------------------------------------


def _state_dir() -> Path:
    env = os.environ.get(STATE_DIR_ENV)
    if env:
        return Path(env)
    base = os.environ.get("LARRY_STATE_DIR")
    if base:
        return Path(base) / "extern-taint"
    return Path(os.environ.get("VAULT_PATH", ".")) / "data" / "extern-taint"


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:80] or "unknown"
    return _state_dir() / f"{safe}.json"


def load(session_id: str) -> dict:
    try:
        return json.loads(_state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"first": None, "count": 0, "sources": []}


def tainted(session_id: str) -> bool:
    return bool(session_id) and load(session_id)["count"] > 0


def record(session_id: str, source: str) -> dict:
    """Note a read from outside. Returns the session state afterwards."""
    state = load(session_id)
    now = datetime.now().isoformat(timespec="seconds")
    state["first"] = state.get("first") or now
    state["count"] = int(state.get("count", 0)) + 1
    state["sources"] = ([{"at": now, "source": source}] + state.get("sources", []))[:MAX_SOURCES]
    p = _state_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    if state["count"] == 1:
        _sweep(p.parent)
    return state


def _sweep(directory: Path) -> None:
    cutoff = time.time() - STATE_TTL_SECONDS
    try:
        for f in directory.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass


# -- Mode, verdict and shadow log -------------------------------------------


def mode() -> str:
    return "shadow" if (os.environ.get(MODE_ENV) or "").strip().lower() == "shadow" else "enforce"


def is_headless() -> bool:
    return os.environ.get(HEADLESS_ENV) == "1"


def verdict(session_id: str, oversight_mode: str, *, internal: bool = False,
            marker: bool = False) -> dict | None:
    """What a read from outside means for an action that oversight set to
    oversight_mode (the mode WITHOUT markers). None if it changes nothing:
    the session is clean, the action is internal, or it is already in_loop
    and no marker tries to lift it past that.

    Returns {"raise": bool, "reason": str, "state": dict}. raise is true only
    in enforce and only headless."""
    if internal or not tainted(session_id):
        return None
    if oversight_mode == "in_loop" and not marker:
        return None
    state = load(session_id)
    latest = state["sources"][0]["source"] if state.get("sources") else "unknown source"
    reason = (f"the session has read text from outside ({state['count']} reads, latest {latest}). "
              f"An outward action after that needs the owner's yes.")
    return {"raise": mode() == "enforce" and is_headless(), "reason": reason, "state": state}


def log_shadow(session_id: str, action: str, target: str, oversight_mode: str,
               state: dict, raised: bool, marker: bool = False) -> None:
    row = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "session": session_id,
        "headless": is_headless(),
        "raised": raised,
        "action": action,
        "target": target,
        "mode": oversight_mode,
        "marker": marker,
        "reads": state.get("count", 0),
        "sources": [s["source"] for s in state.get("sources", [])[:3]],
    }
    f = _state_dir() / "shadow.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _main() -> None:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="Extern taint: outward actions after reading outside text")
    parser.add_argument("cmd", choices=["shadow"])
    parser.add_argument("-n", type=int, default=30)
    args = parser.parse_args()
    f = _state_dir() / "shadow.jsonl"
    if not f.exists():
        print("No rows logged.")
        return
    for line in f.read_text(encoding="utf-8").splitlines()[-args.n:]:
        r = json.loads(line)
        who = "headless" if r["headless"] else "interactive"
        mark = " owner-ok" if r.get("marker") else ""
        print(f"{r['at']}  {who:<11} {r['action']} ({r['mode']}{mark}) -> {r['target']}\n"
              f"    {r['reads']} reads: {', '.join(r['sources'])}")


if __name__ == "__main__":
    _main()
