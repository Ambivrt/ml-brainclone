"""skill_usage.py -- which skills are actually used, and when last.

Borrowed from Hermes Agent 0.22 (unused skills are archived after 30 days),
with the owner as gatekeeper: nothing is archived here. skill_lint reads the
log and lists the candidates in the nightly report, the owner decides.

Two ways of using a skill count:
  the Skill tool        -> the name that was called ("my-skill", "plugin:brainstorming")
  Read of a skill file  -> the file name without .md when the file sits
                           directly in a `skills/` directory, the folder name
                           when the file is called SKILL.md (also .claude/skills/)

The hook scripts/hooks/skill-usage.py calls record(). The log is one JSONL
row per use, in LARRY_SKILL_USAGE_LOG, else
$LARRY_STATE_DIR/skill-usage/usage.jsonl, else
$VAULT_PATH/data/skill-usage/usage.jsonl.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

LOG_ENV = "LARRY_SKILL_USAGE_LOG"
# Files in a skills directory that are not skills.
NOT_SKILLS = {"index", "skills-index", "skill-spec", "readme"}


def log_path() -> Path:
    env = os.environ.get(LOG_ENV)
    if env:
        return Path(env)
    base = os.environ.get("LARRY_STATE_DIR")
    root = Path(base) if base else Path(os.environ.get("VAULT_PATH", ".")) / "data"
    return root / "skill-usage" / "usage.jsonl"


def skill_from_payload(payload: dict) -> str | None:
    """The skill name a tool call used, or None."""
    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return None
    if tool == "Skill":
        name = str(ti.get("skill") or "").strip().lstrip("/")
        return name or None
    if tool != "Read":
        return None
    p = str(ti.get("file_path") or "").replace("\\", "/")
    low = p.lower()
    if not low.endswith(".md"):
        return None
    parts = p.split("/")
    if parts[-1] == "SKILL.md" and len(parts) >= 2 and "/skills/" in low:
        return parts[-2]
    if len(parts) >= 2 and parts[-2].lower() == "skills":
        stem = parts[-1][:-3]
        return None if stem.lower() in NOT_SKILLS else stem
    return None


def record(payload: dict, now: datetime | None = None) -> str | None:
    name = skill_from_payload(payload)
    if not name:
        return None
    row = {"ts": (now or datetime.now()).isoformat(timespec="seconds"), "skill": name,
           "via": payload.get("tool_name"), "session": payload.get("session_id", "")}
    f = log_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return name


def summary(path: Path | None = None) -> tuple[datetime | None, dict[str, datetime]]:
    """(first row of the log, {skill: last used}). Names with a plugin prefix
    also count under their short name, `plugin:rescue` also becomes `rescue`."""
    first: datetime | None = None
    last: dict[str, datetime] = {}
    try:
        lines = (path or log_path()).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, {}
    for line in lines:
        try:
            row = json.loads(line)
            ts = datetime.fromisoformat(row["ts"])
            name = str(row["skill"])
        except (ValueError, KeyError, TypeError):
            continue
        first = ts if first is None or ts < first else first
        for n in {name, name.split(":")[-1]}:
            if n not in last or ts > last[n]:
                last[n] = ts
    return first, last
