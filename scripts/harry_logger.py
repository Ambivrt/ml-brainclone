"""
harry_logger.py — shared transcript-logger for all Harry (audio) agents.

Every voice/text exchange is appended to `_private/live-transcript-log.md`
so there is a permanent record of everything said and answered.

Rule: BOTH user input (transcribed from STT) AND agent replies must be
saved as text. Nothing may be lost. All Harry scripts should import this
module instead of writing to the log file directly.

Setup:
  export VAULT_PATH=/path/to/your/vault
  # or edit TRANSCRIPT_LOG below to point to a hard-coded path
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_PATH", "."))
TRANSCRIPT_LOG = VAULT / "_private" / "live-transcript-log.md"

_HEADER = (
    "---\ntags: [voice, level4]\nstatus: active\n"
    f"created: {datetime.now().strftime('%Y-%m-%d')}\nprivacy: 4\n---\n\n"
    "# Live Transcript Log\n\n"
)


def _ensure_file() -> None:
    TRANSCRIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not TRANSCRIPT_LOG.exists():
        TRANSCRIPT_LOG.write_text(_HEADER, encoding="utf-8")


def log_transcript(role: str, text: str, source: str = "") -> None:
    """Append a single turn (user or agent) to the transcript log.

    role:   "User" or agent name ("Larry", "Harry", ...)
    text:   full text — never truncate here
    source: optional marker for which script/channel (e.g. "harry-voice", "mcp")
    """
    if not text:
        return
    _ensure_file()
    now = datetime.now().strftime("%H:%M:%S")
    tag = f" ({source})" if source else ""
    try:
        with open(TRANSCRIPT_LOG, "a", encoding="utf-8") as f:
            f.write(f"**[{now}] {role}{tag}:** {text}\n\n")
    except Exception:
        pass


def log_session_header(source: str, extra: str = "") -> None:
    """Write a session header so a new run is easy to spot in the log."""
    _ensure_file()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"\n## Session {stamp} — {source}"
    if extra:
        line += f" — {extra}"
    line += "\n\n"
    try:
        with open(TRANSCRIPT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
