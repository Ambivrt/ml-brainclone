"""proactive_scanner — session-init detects actionable items and dispatches tasks.

Run from the session-init hook (e.g. load-context.sh) or on demand. Scans four
sources and creates task files in 00-inbox/ via task_lib:

  1. _private/notify-queue.json   → unread photos → Barry sort
                                    → unread voices → Harry transcribe
                                    → unread messages with action keywords
                                      → Larry triage
  2. 00-inbox/                    → files older than 24h without a status line
                                    → Larry triage
  3. _tasks/*/failed/             → tasks failed within the last 12h → Larry
                                    diagnoses the failure
  4. Gmail unread (via gws)       → Larry triages the inbox (never auto-reply)

Output: JSON on stdout so hook scripts can surface a summary.

Safety:
- Dedup against tasks already dispatched today (by title).
- Cap on total dispatches per run (default 10) so an overloaded queue doesn't
  fan out into hundreds of tasks.
- External actions (mail replies, LinkedIn posts) are NEVER dispatched here —
  only internal jobs: sorting, transcription, triage, diagnosis.

ENV:
    VAULT_ROOT  — vault root (defaults to ~/vault if unset)

Run:
    python proactive_scanner.py                  # normal scan
    python proactive_scanner.py --dry-run        # report only
    python proactive_scanner.py --cap 20         # cap dispatches
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import task_lib  # noqa: E402


def _vault_root() -> Path:
    r = os.environ.get("VAULT_ROOT")
    if r:
        return Path(r)
    return Path.home() / "vault"


VAULT_ROOT = _vault_root()
NOTIFY_QUEUE = VAULT_ROOT / "_private" / "notify-queue.json"
INBOX_DIR = VAULT_ROOT / "00-inbox"
TASKS_DIR = VAULT_ROOT / "_tasks"

ACTION_KEYWORDS = {
    "barry": ["image", "generate", "draw", "photo", "render"],
    "harry": ["transcribe", "voice", "audio", "mix", "tts"],
    "larry": ["fix", "triage", "analyse", "summarise", "look up", "write"],
    "tarry": ["remind", "påminn", "deadline", "follow up", "schedule", "klocka", "timer"],
}

STALE_INBOX_HOURS = 24
FAILED_TASK_LOOKBACK_HOURS = 12

_today_tag = datetime.now().strftime("%Y%m%d")


def _existing_titles_today() -> set[str]:
    """Titles of tasks already dispatched today (across all buckets)."""
    seen: set[str] = set()
    prefix_today = f"-{_today_tag}-"
    for p in INBOX_DIR.glob("task-*.md"):
        if prefix_today not in p.name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
            m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if m:
                seen.add(m.group(1).strip().lower())
        except Exception:
            pass
    for agent in ("larry", "harry", "barry", "parry"):
        for bucket in ("processing", "done", "failed"):
            d = TASKS_DIR / agent / bucket
            if not d.exists():
                continue
            for p in d.glob("task-*.md"):
                if prefix_today not in p.name:
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
                    if m:
                        seen.add(m.group(1).strip().lower())
                except Exception:
                    pass
    return seen


def _dispatch(agent: str, title: str, desc: str, source: str,
              dry_run: bool, dispatched: list[dict]) -> None:
    if dry_run:
        dispatched.append({"agent": agent, "title": title, "source": source,
                           "dry_run": True})
        return
    try:
        path = task_lib.create_task(agent, title, desc,
                                    from_source=source, priority="normal")
        dispatched.append({"agent": agent, "title": title, "source": source,
                           "path": str(path)})
    except Exception as e:
        dispatched.append({"agent": agent, "title": title, "source": source,
                           "error": str(e)})


def _scan_notify_queue(dedup, dispatched, dry_run, cap):
    if not NOTIFY_QUEUE.exists():
        return
    try:
        items = json.loads(NOTIFY_QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(items, list):
        return

    unread = [it for it in items if isinstance(it, dict)
              and not it.get("read", False)]
    if not unread:
        return

    photos = [it for it in unread if it.get("type") == "photo"]
    voices = [it for it in unread if it.get("type") == "voice"]
    messages = [it for it in unread if it.get("type") == "message"]

    if photos and len(dispatched) < cap:
        title = f"Sort {len(photos)} unsorted notify-queue photo(s)"
        if title.lower() not in dedup:
            desc = (f"notify-queue has {len(photos)} unsorted photos "
                    f"(read=false, type=photo). Run the image-sort pipeline "
                    f"and mark them read=true on completion.")
            _dispatch("barry", title, desc,
                      "proactive-scan-notify-queue", dry_run, dispatched)
            dedup.add(title.lower())

    if voices and len(dispatched) < cap:
        title = f"Transcribe {len(voices)} unprocessed voice message(s)"
        if title.lower() not in dedup:
            desc = (f"notify-queue has {len(voices)} untranscribed voice "
                    f"items. Run the audio pipeline.")
            _dispatch("harry", title, desc,
                      "proactive-scan-notify-queue", dry_run, dispatched)
            dedup.add(title.lower())

    for msg in messages:
        if len(dispatched) >= cap:
            break
        text = (msg.get("text") or "").strip()
        if not text or len(text) < 20:
            continue
        # A classifier upstream (the bot listener) may already have routed the
        # message and tagged it `route_to`. A known agent is used as is. Any other
        # value is the classifier's own "nothing for an agent" verdict and is not
        # routed at all. Only a missing tag falls back to the keyword scan.
        route = msg.get("route_to")
        chosen = None
        if route is not None:
            if route in ACTION_KEYWORDS:
                chosen = route
        else:
            lower = text.lower()
            for agent, keywords in ACTION_KEYWORDS.items():
                if any(kw in lower for kw in keywords):
                    chosen = agent
                    break
        if not chosen:
            continue
        title = f"Follow up on message: {text[:60]}"
        if title.lower() in dedup:
            continue
        _dispatch(chosen, title, text,
                  "proactive-scan-notify-queue", dry_run, dispatched)
        dedup.add(title.lower())


def _scan_stale_inbox(dedup, dispatched, dry_run, cap):
    if not INBOX_DIR.exists():
        return
    cutoff = datetime.now() - timedelta(hours=STALE_INBOX_HOURS)
    stale = []
    for p in INBOX_DIR.glob("*.md"):
        if p.name.startswith(("task-", "morgonbrief-", "telegram-queue-")):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if mtime >= cutoff:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")[:500]
            if "status:" in text:
                continue
            stale.append(p)
        except Exception:
            continue

    if not stale or len(dispatched) >= cap:
        return

    title = f"Triage {len(stale)} un-processed inbox file(s)"
    if title.lower() in dedup:
        return
    desc = (f"00-inbox/ has {len(stale)} files older than "
            f"{STALE_INBOX_HOURS}h without a status line in frontmatter. "
            f"Walk through, categorise, move or archive.")
    _dispatch("larry", title, desc,
              "proactive-scan-stale-inbox", dry_run, dispatched)
    dedup.add(title.lower())


def _scan_failed_tasks(dedup, dispatched, dry_run, cap):
    cutoff = datetime.now() - timedelta(hours=FAILED_TASK_LOOKBACK_HOURS)
    failed = []
    for agent in ("larry", "harry", "barry", "tarry"):
        d = TASKS_DIR / agent / "failed"
        if not d.exists():
            continue
        for p in d.glob("task-*.md"):
            try:
                if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                    continue
                # Expired tasks are moved to failed/ too. They have no error to
                # diagnose and must not spawn a diagnosis task of their own.
                if re.search(r"^status:\s*expired\s*$", p.read_text(encoding="utf-8"), re.M):
                    continue
                failed.append(p)
            except Exception:
                continue

    if not failed or len(dispatched) >= cap:
        return
    title = f"Diagnose {len(failed)} recently failed task(s)"
    if title.lower() in dedup:
        return
    desc = (f"_tasks/*/failed/ has {len(failed)} tasks that failed in the "
            f"last {FAILED_TASK_LOOKBACK_HOURS}h. Read the error sections, "
            f"identify root causes, retry or report systemic breakage.")
    _dispatch("larry", title, desc,
              "proactive-scan-failed-tasks", dry_run, dispatched)
    dedup.add(title.lower())


def _scan_gmail(dedup, dispatched, dry_run, cap):
    if len(dispatched) >= cap:
        return
    try:
        proc = subprocess.run(
            ["gws", "gmail", "users", "messages", "list",
             "--params",
             '{"userId":"me","q":"is:unread category:primary","maxResults":5}'],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except Exception:
        return
    if proc.returncode != 0:
        return
    try:
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return
    count = len(data.get("messages") or [])
    if count == 0:
        return
    title = f"Triage {count} unread Gmail message(s)"
    if title.lower() in dedup:
        return
    desc = (f"Gmail has {count} unread in primary. Read subjects + "
            f"previews, categorise (action / info / trash), create "
            f"follow-up tasks for action mails. NEVER reply without "
            f"approval.")
    _dispatch("larry", title, desc,
              "proactive-scan-gmail", dry_run, dispatched)
    dedup.add(title.lower())


def run(dry_run=False, cap=10):
    dedup = _existing_titles_today()
    dispatched = []

    _scan_notify_queue(dedup, dispatched, dry_run, cap)
    _scan_stale_inbox(dedup, dispatched, dry_run, cap)
    _scan_failed_tasks(dedup, dispatched, dry_run, cap)
    _scan_gmail(dedup, dispatched, dry_run, cap)

    by_agent = {}
    for d in dispatched:
        if "error" in d:
            continue
        by_agent[d["agent"]] = by_agent.get(d["agent"], 0) + 1

    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": dry_run, "cap": cap,
        "total": len([d for d in dispatched if "error" not in d]),
        "by_agent": by_agent, "dispatched": dispatched,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cap", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run, cap=args.cap),
                     indent=2, ensure_ascii=False))
