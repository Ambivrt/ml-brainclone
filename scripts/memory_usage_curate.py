"""memory_usage_curate.py -- nightly aggregation of memory usage evidence.

Part 2 of usage-driven memory curation ("dreaming", see docs/memory-system.md).

Deterministic (no LLM). Run as a pre-collect step before the nightly memory
batch -- the LLM batch then weighs usage evidence into its curation decisions.

- Aggregates .usage/usage.jsonl per memory file (reads 30d, total, last read)
- Cross-references every .md in the memory dir -> cold files (zero reads)
- Trims the log to 90 days
- Writes the report into a private, non-synced location: memory file NAMES
  can leak sensitive topics, so keep the report out of any synced inbox

Configure via env:
  MEMORY_DIR    -- auto-memory directory (default: ./memory)
  USAGE_REPORT  -- report path (default: <MEMORY_DIR>/.usage/report.md)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

MEMORY_ROOT = Path(os.environ.get("MEMORY_DIR", "./memory"))
USAGE_LOG = MEMORY_ROOT / ".usage" / "usage.jsonl"
REPORT = Path(os.environ.get("USAGE_REPORT", str(MEMORY_ROOT / ".usage" / "report.md")))

IGNORE_NAMES = {"MEMORY.md", "USER.md"}
HOT_WINDOW_DAYS = 30
NEW_GRACE_DAYS = 30      # files younger than this are never classified cold
LOG_RETENTION_DAYS = 90
HOT_TOP_N = 15


def load_events(path: Path = USAGE_LOG) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            datetime.fromisoformat(ev["ts"])  # validate
            events.append(ev)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue  # corrupt lines are ignored and rotated away
    return events


def aggregate(events: list[dict], now: datetime) -> dict[str, dict]:
    """file -> {reads_30d, reads_total, last_read}"""
    cutoff = now - timedelta(days=HOT_WINDOW_DAYS)
    stats: dict[str, dict] = {}
    for ev in events:
        ts = datetime.fromisoformat(ev["ts"])
        s = stats.setdefault(ev["file"], {"reads_30d": 0, "reads_total": 0, "last_read": ts})
        s["reads_total"] += 1
        if ts >= cutoff:
            s["reads_30d"] += 1
        if ts > s["last_read"]:
            s["last_read"] = ts
    return stats


def memory_files(root: Path = MEMORY_ROOT) -> dict[str, datetime]:
    """relative path -> created (frontmatter field, mtime fallback)."""
    out: dict[str, datetime] = {}
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".usage/") or p.name in IGNORE_NAMES:
            continue
        created = None
        try:
            head = p.read_text(encoding="utf-8")[:600]
            for line in head.splitlines():
                if line.startswith("created:"):
                    created = datetime.fromisoformat(line.split(":", 1)[1].strip().strip("'\"")[:10])
                    break
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        out[rel] = created or datetime.fromtimestamp(p.stat().st_mtime)
    return out


def classify(stats: dict[str, dict], files: dict[str, datetime], now: datetime):
    """-> (hot, cold, fresh). Cold = zero reads and older than the grace window."""
    grace = now - timedelta(days=NEW_GRACE_DAYS)
    hot = sorted(
        ((f, s) for f, s in stats.items() if s["reads_30d"] > 0 and f in files),
        key=lambda kv: (-kv[1]["reads_30d"], kv[0]),
    )[:HOT_TOP_N]
    cold = sorted(f for f, created in files.items() if f not in stats and created < grace)
    fresh = sorted(f for f, created in files.items() if f not in stats and created >= grace)
    return hot, cold, fresh


def rotate_log(events: list[dict], now: datetime, path: Path = USAGE_LOG) -> int:
    cutoff = now - timedelta(days=LOG_RETENTION_DAYS)
    kept = [ev for ev in events if datetime.fromisoformat(ev["ts"]) >= cutoff]
    if path.exists():
        path.write_text(
            "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in kept),
            encoding="utf-8", newline="\n",
        )
    return len(events) - len(kept)


def render(hot, cold, fresh, total_events: int, now: datetime) -> str:
    date = now.strftime("%Y-%m-%d")
    lines = [
        "---",
        "tags: [generated/nightly, system/memory]",
        "status: draft",
        f"created: {date}",
        "privacy: 3",
        "---",
        "",
        f"# Memory usage -- {date}",
        "",
        f"Source: {total_events} logged reads (rolling {LOG_RETENTION_DAYS} days). "
        "Consumed by the nightly memory batch for evidence-based curation. "
        "Cold memories get their index line moved to the archive section -- never deleted.",
        "",
        f"## HOT -- most read last {HOT_WINDOW_DAYS}d",
        "",
    ]
    if hot:
        lines += ["| Memory | 30d | Total | Last |", "|---|---|---|---|"]
        for f, s in hot:
            lines.append(f"| {f} | {s['reads_30d']} | {s['reads_total']} | {s['last_read'].strftime('%Y-%m-%d')} |")
    else:
        lines.append("No reads logged yet.")
    lines += ["", f"## COLD -- zero reads, older than {NEW_GRACE_DAYS}d ({len(cold)})", ""]
    lines += [f"- {f}" for f in cold] or ["None."]
    lines += ["", f"## FRESH -- created <{NEW_GRACE_DAYS}d ago, too early to judge ({len(fresh)})", ""]
    lines += [f"- {f}" for f in fresh] or ["None."]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now()
    events = load_events()
    stats = aggregate(events, now)
    files = memory_files()
    hot, cold, fresh = classify(stats, files, now)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(hot, cold, fresh, len(events), now), encoding="utf-8", newline="\n")
    dropped = rotate_log(events, now)
    print(f"memory-usage: {len(events)} events, {len(hot)} hot, {len(cold)} cold, "
          f"{len(fresh)} fresh, {dropped} rotated. Report: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
