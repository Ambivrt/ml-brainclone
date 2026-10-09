"""inbox_reaper.py -- puts a ceiling on 00-inbox/.

The problem it solves: a nightly automation that writes reports into the inbox
produces files faster than anyone consumes them. Left alone the inbox grows
without bound, and the triage batch ends up triaging its own output.

This moves auto-generated reports that have outlived the inbox to
06-archive/<type>/YYYY-MM/. The type comes from the filename prefix: a nightly
report belongs with nightly reports, whatever folder it passed through. There
is never a 06-archive/inbox/: the inbox is a queue, not a category, and a
folder called "inbox" inside the archive hides work that was never done.
See docs/vault-hygiene.md.

Safety principles:
  1. Only filenames matching known auto-generated patterns are touched.
     Anything you wrote yourself is left alone regardless of age.
  2. Dry-run is the default. Nothing moves without --apply.
  3. `pinned: true` or `kg-state: pending` in frontmatter protects a file.
     `status: active` does not: templates set it, so it says nothing about
     whether anyone still needs the file.
  4. Move, never delete. A name collision gets a suffix, never an overwrite.
  5. `privacy` 3 or 4 in frontmatter goes to _private/06-archive/, never the
     shared archive. The level follows the content, not the folder. A missing
     field is treated as shared.
  6. Knowledge-graph update files that have been applied leave the inbox at
     once: the graph keeps its own timeline. Files with open [UNSURE] lines or
     `kg-state: partial` wait for the owner and stay, whatever their age.

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
    re.compile(r"^scaffold-sync-report-\d{4}-\d{2}-\d{2}\.md$"),
    re.compile(r"^prompt-audit-.*\.md$"),
    re.compile(r"^task-\w+-\d{8}-.*\.md$"),
]

# Prefix -> archive bucket. First match wins.
ARCHIVE_MAP = [
    (re.compile(r"^nightly-report-"), "nightly-reports"),
    (re.compile(r"^kg-"), "kg"),
    (re.compile(r"^distillate-"), "distillates"),
    (re.compile(r"^morning-brief-"), "morning-briefs"),
    (re.compile(r"^scaffold-sync-"), "scaffold-sync"),
    (re.compile(r"^prompt-audit-"), "prompt-audit"),
    (re.compile(r"^task-"), "tasks"),
]
DEFAULT_BUCKET = "auto-reports"

# Frontmatter fields that protect a file from archiving regardless of age.
KEEP_IF = [
    re.compile(r"^pinned:\s*true\s*$", re.MULTILINE),
    re.compile(r"^kg-state:\s*pending\s*$", re.MULTILINE),
]

PRIVATE_FROM = 3
PRIVACY_FIELD = re.compile(r"^privacy:\s*([1-4])\s*$", re.MULTILINE)

KG_NAME = re.compile(r"^kg-(?:updates|auto-extract)-\d{4}-\d{2}-\d{2}\.md$")
KG_APPLIED = re.compile(r"^kg-state:\s*applied\s*$", re.MULTILINE)
KG_PARTIAL = re.compile(r"^kg-state:\s*partial\s*$", re.MULTILINE)
KG_UNSURE_OPEN = re.compile(r"^\s*- \[ \] .*\[UNSURE\]", re.MULTILINE)

DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def is_auto_generated(name: str) -> bool:
    return any(p.match(name) for p in AUTO_PATTERNS)


def frontmatter(text: str) -> str:
    """The block between the --- lines, empty if there is none.

    Only the block counts, never the body -- otherwise a report that quotes
    'pinned: true' or 'privacy: 4' in a code fence would act on itself.
    """
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return "" if end == -1 else text[3:end]


def is_protected(text: str) -> bool:
    fm = frontmatter(text)
    return bool(fm) and any(p.search(fm) for p in KEEP_IF)


def privacy_level(text: str) -> int | None:
    m = PRIVACY_FIELD.search(frontmatter(text))
    return int(m.group(1)) if m else None


def is_applied_kg(name: str, text: str) -> bool:
    """An applied graph-update file with no open [UNSURE] lines."""
    return (bool(KG_NAME.match(name)) and bool(KG_APPLIED.search(frontmatter(text)))
            and not KG_UNSURE_OPEN.search(text))


def kg_waits_on_owner(name: str, text: str) -> bool:
    """Open [UNSURE] lines or kg-state: partial. Stays in the inbox at any age."""
    return bool(KG_NAME.match(name)) and (
        bool(KG_UNSURE_OPEN.search(text)) or bool(KG_PARTIAL.search(frontmatter(text))))


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


def archive_target(vault: Path, path: Path, today: date) -> Path:
    """06-archive/<type>/YYYY-MM/<name>, or under _private/ for level 3-4.
    The file is read here so a dry-run shows the same target as --apply."""
    bucket = DEFAULT_BUCKET
    for pattern, name in ARCHIVE_MAP:
        if pattern.match(path.name):
            bucket = name
            break
    m = DATE_IN_NAME.search(path.name)
    month = f"{m.group(1)}-{m.group(2)}" if m else today.strftime("%Y-%m")
    try:
        level = privacy_level(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        level = None
    root = vault / "_private" if level is not None and level >= PRIVATE_FROM else vault
    return root / "06-archive" / bucket / month / path.name


def unique(dest: Path) -> Path:
    """A free name next to dest: name-2.md, name-3.md ..."""
    if not dest.exists():
        return dest
    n = 2
    while True:
        cand = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
        if not cand.exists():
            return cand
        n += 1


def collect(vault: Path, days: int, today: date) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Returns (to_move, skipped_with_reason)."""
    inbox = vault / "00-inbox"
    to_move, skipped = [], []
    for path in sorted(inbox.glob("*.md")):
        if not is_auto_generated(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped.append((path, f"unreadable: {exc}"))
            continue
        if is_applied_kg(path.name, text) and not is_protected(text):
            to_move.append(path)
            continue
        if file_age_days(path, today) < days:
            continue
        if is_protected(text):
            skipped.append((path, "protected by frontmatter"))
            continue
        if kg_waits_on_owner(path.name, text):
            skipped.append((path, "graph lines wait for the owner"))
            continue
        to_move.append(path)
    return to_move, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Archive expired auto-generated reports from 00-inbox to 06-archive/<type>/YYYY-MM/")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"lifetime in days (default {DEFAULT_DAYS})")
    ap.add_argument("--apply", action="store_true",
                    help="actually move (without this: dry-run)")
    args = ap.parse_args(argv)

    vault = Path(args.vault)
    today = date.today()

    to_move, skipped = collect(vault, args.days, today)
    remaining = len(list((vault / "00-inbox").glob("*.md"))) - len(to_move)

    mode = "MOVING" if args.apply else "DRY-RUN (nothing moved)"
    print(f"inbox-reaper [{mode}] lifetime={args.days}d")
    print(f"  to archive   : {len(to_move)}")
    print(f"  skipped      : {len(skipped)}")
    print(f"  left in inbox: {remaining}")

    for path, reason in skipped:
        print(f"  [skip] {path.name}: {reason}")

    for path in to_move:
        dest = unique(archive_target(vault, path, today))
        if args.apply:
            dest.parent.mkdir(parents=True, exist_ok=True)
            path.replace(dest)
            print(f"  [moved] {path.name} -> {dest.relative_to(vault)}")
        else:
            print(f"  [would move] {path.name} -> {dest.relative_to(vault)}")

    if not args.apply and to_move:
        print("\nRun with --apply to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
