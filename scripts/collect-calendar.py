"""collect-calendar.py -- fetches today's calendar events, deterministically.

Writes .data/calendar-today.json before the morning brief session runs. See
docs/security-untrusted-input.md.

Why this is a separate step instead of letting the brief session call the
calendar API itself: the brief session also reads other untrusted text
(social scan output, calendar event descriptions written by whoever sent the
invite). If that same session also held a live calendar/mail tool, an
embedded instruction in a meeting description or a scraped post could reach
a session that could act on it. Fetching the calendar here, with plain code
and no LLM in the loop, means the brief session only ever gets to READ the
result, with tools that cannot act on what it reads (--tools Read,Glob,Grep
in nightly-runner.sh's read-only mode).

Robustness: a failure fetching one calendar yields an empty event list for
that calendar plus a line on stderr, never a crash. A failure listing
calendars at all falls back to just "primary". The script always exits 0
(best effort) -- a broken calendar source must never stop the nightly run or
the brief.

Requires the `gws` CLI (Google Workspace CLI) to be installed and
authenticated. See docs/larry-setup.md.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GWS_TIMEOUT = 30
MAX_EVENTS_PER_CALENDAR = 50
MAX_DESCRIPTION_CHARS = 2000

VAULT_PATH = os.environ.get("VAULT_PATH", ".")
DATA_DIR = Path(os.environ.get(
    "NIGHTLY_DATA_DIR",
    str(Path(VAULT_PATH) / "03-projects" / "ml-brainclone" / "operations" / "nattskift" / ".data"),
))
OUT_FILE = DATA_DIR / "calendar-today.json"

# Same pattern as other subprocess calls in this scaffold: without this, a
# console window flashes for every gws call when the nightly run is
# headless (scheduled task, no interactive shell).
_SUBPROCESS_NOWINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}


def _run_gws(args: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["gws"] + args,
            capture_output=True, text=True, timeout=GWS_TIMEOUT,
            encoding="utf-8", errors="replace",
            **_SUBPROCESS_NOWINDOW,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or "").strip()[:300]
    return True, result.stdout


def list_calendars() -> list[dict]:
    """All calendars (primary + imported). Error or empty -- just primary."""
    ok, raw = _run_gws([
        "calendar", "calendarList", "list",
        "--params", json.dumps({"maxResults": 50}),
    ])
    if not ok:
        print(f"WARNING: calendarList failed ({raw}) -- falling back to primary only",
              file=sys.stderr)
        return [{"id": "primary", "summary": "primary"}]
    try:
        data = json.loads(raw)
        items = data.get("items", [])
        cals = [
            {"id": c["id"], "summary": c.get("summary", c["id"])}
            for c in items if c.get("id")
        ]
        return cals if cals else [{"id": "primary", "summary": "primary"}]
    except Exception as exc:
        print(f"WARNING: calendarList parse failed ({exc}) -- falling back to primary only",
              file=sys.stderr)
        return [{"id": "primary", "summary": "primary"}]


def fetch_events(calendar_id: str) -> list[dict]:
    """Today's events (00:00-23:59, local time) for one calendar."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
    ok, raw = _run_gws([
        "calendar", "events", "list", "--params", json.dumps({
            "calendarId": calendar_id,
            "timeMin": start,
            "timeMax": end,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": MAX_EVENTS_PER_CALENDAR,
        })
    ])
    if not ok:
        print(f"WARNING: events list failed for {calendar_id} ({raw})", file=sys.stderr)
        return []
    try:
        data = json.loads(raw)
        events = []
        for ev in data.get("items", []):
            start_obj = ev.get("start", {}) or {}
            end_obj = ev.get("end", {}) or {}
            events.append({
                "summary": ev.get("summary", "(no title)"),
                "start": start_obj.get("dateTime", start_obj.get("date", "")),
                "end": end_obj.get("dateTime", end_obj.get("date", "")),
                "all_day": "date" in start_obj,
                "location": ev.get("location", ""),
                # UNTRUSTED DATA: free text written by the meeting organizer
                # or another sender, not by the user. Read by the brief
                # session as plain information, never as an instruction --
                # see the UNTRUSTED DATA section in the morning brief prompt.
                "description": (ev.get("description") or "")[:MAX_DESCRIPTION_CHARS],
            })
        return events
    except Exception as exc:
        print(f"WARNING: events parse failed for {calendar_id} ({exc})", file=sys.stderr)
        return []


def collect() -> dict:
    calendars = list_calendars()
    result: dict = {"date": datetime.now().strftime("%Y-%m-%d"), "calendars": []}
    for cal in calendars:
        events = fetch_events(cal["id"])
        result["calendars"].append({
            "id": cal["id"],
            "summary": cal["summary"],
            "events": events,
        })
    return result


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result = collect()
    # Atomic write (temp file + os.replace), same pattern as
    # scripts/brief_output.py -- a reader (the brief session, a quality
    # gate) must never see a partially written file, and an interruption
    # mid-write must never leave a broken calendar-today.json behind.
    tmp_path = OUT_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp_path), str(OUT_FILE))
    total_events = sum(len(c["events"]) for c in result["calendars"])
    print(f"calendar-today.json written: {len(result['calendars'])} calendars, {total_events} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
