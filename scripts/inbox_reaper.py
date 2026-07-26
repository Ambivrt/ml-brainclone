"""inbox_reaper.py -- puts a ceiling on 00-inbox/.

The problem it solves: a nightly automation that writes reports into the inbox
produces files faster than anyone consumes them. Left alone the inbox grows
without bound, and the triage batch ends up triaging its own output.

This deletes auto-generated reports that have outlived their usefulness.

It deletes rather than archives, deliberately. Moving expired inbox files to
06-archive/inbox/ creates a folder whose name is a contradiction, hides work
that was never done, and doubles every file. The inbox is a queue: triage it
and empty it. See docs/vault-hygiene.md.

Deletion is safe for what this touches. The files are regenerable reports in a
git-tracked folder, so anything needed is in history. Content worth keeping
belongs in a topic folder, and moving it there is the triage step's job, not
this script's.

Safety principles:
  1. Only filenames matching known auto-generated patterns are touched.
     Anything you wrote yourself is left alone regardless of age.
  2. Dry-run is the default. Nothing is deleted without --apply.
  3. Files with `status: active` or `pinned: true` in frontmatter are skipped
     even when they match a pattern and are old.

Usage:
    python inbox_reaper.py                 # dry-run, shows what would happen
    python inbox_reaper.py --apply         # do it
    python inbox_reaper.py --days 14       # custom lifetime
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

DEFAULT_VAULT = Path(".")
DEFAULT_DAYS = 30

# Auto-generated filename patterns. Only these are touched. Add new patterns
# here as your nightly run grows -- err on the side of too narrow.
AUTO_PATTERNS = [
    re.compile(r"^nightly-report-.*\.md$"),
    re.compile(r"^kg-updates?-\d{4}-\d{2}-\d{2}\.md$"),
    re.compile(r"^kg-auto-extract-\d{4}-\d{2}-\d{2}\.md$"),
    re.compile(r"^kg-decisions-\d{4}-\d{2}-\d{2}\.md$"),
    re.compile(r"^distillate-\d{4}-\d{2}-\d{2}\.md$"),
    re.compile(r"^morning-brief-\d{4}-\d{2}-\d{2}(-v\d+)?\.md$"),
    re.compile(r"^task-\w+-\d{8}-.*\.md$"),
]

# Frontmatter fields that protect a file from deletion regardless of age.
KEEP_IF = [
    re.compile(r"^status:\s*active\s*$", re.MULTILINE),
    re.compile(r"^pinned:\s*true\s*$", re.MULTILINE),
]

DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def is_auto_generated(name: str) -> bool:
    return any(p.match(name) for p in AUTO_PATTERNS)


def is_protected(text: str) -> bool:
    """Protected if frontmatter says status: active or pinned: true.

    Reads the frontmatter block only, never the body -- otherwise a report that
    quotes 'status: active' in a code fence would accidentally protect itself.
    """
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    return any(p.search(text[3:end]) for p in KEEP_IF)


def file_age_days(path: Path, today: date) -> int:
    """Age in days. A date in the filename beats mtime.

    This matters more than it looks. A nightly frontmatter normalizer touches
    every inbox file, so mtime is always fresh even on months-old reports.
    Trusting mtime alone means nothing ever expires.
    """
    m = DATE_IN_NAME.search(path.name)
    if m:
        try:
            stamp = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return (today - stamp).days
        except ValueError:
            pass
    return (today - datetime.fromtimestamp(path.stat().st_mtime).date()).days


def collect(vault: Path, days: int, today: date) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Returns (to_delete, skipped_with_reason)."""
    inbox = vault / "00-inbox"
    to_delete, skipped = [], []
    for path in sorted(inbox.glob("*.md")):
        if not is_auto_generated(path.name):
            continue
        if file_age_days(path, today) < days:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped.append((path, f"unreadable: {exc}"))
            continue
        if is_protected(text):
            skipped.append((path, "protected by frontmatter"))
            continue
        to_delete.append(path)
    return to_delete, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Delete expired auto-generated reports from 00-inbox")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"lifetime in days (default {DEFAULT_DAYS})")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (without this: dry-run)")
    args = ap.parse_args(argv)

    vault = Path(args.vault)
    today = date.today()

    to_delete, skipped = collect(vault, args.days, today)
    remaining = len(list((vault / "00-inbox").glob("*.md"))) - len(to_delete)

    mode = "DELETING" if args.apply else "DRY-RUN (nothing deleted)"
    print(f"inbox-reaper [{mode}] lifetime={args.days}d")
    print(f"  to delete    : {len(to_delete)}")
    print(f"  skipped      : {len(skipped)}")
    print(f"  left in inbox: {remaining}")

    for path, reason in skipped:
        print(f"  [skip] {path.name}: {reason}")

    for path in to_delete:
        if args.apply:
            path.unlink()
            print(f"  [deleted] {path.name}")
        else:
            print(f"  [would delete] {path.name}")

    if not args.apply and to_delete:
        print("\nRun with --apply to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
