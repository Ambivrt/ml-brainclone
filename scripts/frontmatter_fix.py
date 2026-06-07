"""frontmatter_fix.py -- fixes the failure classes frontmatter_check.py flags.

Four classes:
  1. embedded/leading BOM      -> stripped BEFORE block analysis (a BOM in
     front of an existing block makes the block look missing; prepending a
     new one would create double frontmatter)
  2. missing frontmatter block -> builds a complete block (tags from path,
     created from filename date or mtime, privacy from folder heuristics)
  3. missing field             -> adds only the missing field
  4. invalid status            -> maps semantically (see STATUS_MAP); when the
     original value carries workflow meaning, preserve it in a custom field
     instead of losing it (example: kg-state below)

Run: python frontmatter_fix.py [--dry-run]
Preserves all content and existing field values exactly.

Configure via env:
  VAULT_ROOT  -- vault path (default: current directory)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontmatter_check import VAULT, EXCLUDE_DIRS, SKIP_NAMES, REQUIRED, FM_RE, check_file

# Invalid status -> valid. Adapt to whatever ad-hoc values your vault grew.
STATUS_MAP = {
    "pending": "draft",
    "applied": "done",
    "parked": "archived",
    "living": "active",
    "design": "draft",
    "ready-to-execute": "active",
}

# Statuses whose original value carries machine-readable workflow state:
# preserved in a separate field instead of being silently dropped.
PRESERVE_IN_FIELD = {"pending": "kg-state", "applied": "kg-state"}

DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def guess_privacy(rel: str) -> int:
    r = rel.lower()
    if "_private/" in r:
        return 3
    if r.startswith(("02-work/", "01-personal/", "05-templates/")):
        return 2
    return 1


def guess_tags(rel: str) -> list[str]:
    """Derive hierarchical tags from the path. Extend per your taxonomy."""
    parts = rel.split("/")
    top = parts[0].lower()
    mapping = {
        "00-inbox": ["inbox"],
        "01-personal": ["personal"],
        "02-work": ["work"],
        "04-knowledge": ["knowledge"],
        "06-archive": ["archive"],
        "_private": ["private"],
    }
    if top == "03-projects" and len(parts) > 2:
        return [f"project/{parts[1]}"]
    return mapping.get(top, ["vault/note"])


def file_created(path: Path) -> str:
    m = DATE_IN_NAME.search(path.name)
    if m:
        return m.group(1)
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def default_status(rel: str) -> str:
    return "archived" if rel.startswith("06-archive/") else "draft"


def build_block(path: Path, rel: str) -> str:
    tags = ", ".join(guess_tags(rel))
    return (
        "---\n"
        f"tags: [{tags}]\n"
        f"status: {default_status(rel)}\n"
        f"created: {file_created(path)}\n"
        f"privacy: {guess_privacy(rel)}\n"
        "---\n\n"
    )


def fix_file(path: Path, rel: str, errors: list[str], dry: bool) -> list[str]:
    """Returns the list of actions performed."""
    text = path.read_text(encoding="utf-8")
    actions: list[str] = []

    if "﻿" in text:
        text = text.replace("﻿", "")
        actions.append("BOM stripped")
        errors = [e for e in errors if "BOM" not in e]
        if not errors and not FM_RE.match(text):
            errors = ["missing frontmatter block"]

    if any("missing frontmatter block" in e for e in errors):
        text = build_block(path, rel) + text
        actions.append("block added")
    else:
        m = FM_RE.match(text)
        fm = m.group(1)
        new_fm = fm

        defaults = {
            "tags": f"tags: [{', '.join(guess_tags(rel))}]",
            "status": f"status: {default_status(rel)}",
            "created": f"created: {file_created(path)}",
            "privacy": f"privacy: {guess_privacy(rel)}",
        }
        for field in REQUIRED:
            if not re.search(rf"^{field}\s*:", new_fm, re.MULTILINE):
                new_fm = new_fm + "\n" + defaults[field]
                actions.append(f"{field} added")

        sm = re.search(r"^status\s*:\s*(\S+)\s*$", new_fm, re.MULTILINE)
        if sm:
            status = sm.group(1).strip().strip('"').strip("'")
            if status in STATUS_MAP:
                replacement = f"status: {STATUS_MAP[status]}"
                if status in PRESERVE_IN_FIELD:
                    replacement += f"\n{PRESERVE_IN_FIELD[status]}: {status}"
                new_fm = new_fm[: sm.start()] + replacement + new_fm[sm.end():]
                actions.append(f"status: {status} -> {STATUS_MAP[status]}")

        if new_fm != fm:
            text = text[: m.start(1)] + new_fm + text[m.end(1):]

    if actions and not dry:
        path.write_text(text, encoding="utf-8", newline="\n")
    return actions


def main() -> int:
    dry = "--dry-run" in sys.argv
    fixed = 0
    for path in sorted(VAULT.rglob("*.md")):
        rel = path.relative_to(VAULT).as_posix()
        if any(rel.startswith(part) or f"/{part}" in f"/{rel}" for part in EXCLUDE_DIRS):
            continue
        if path.name in SKIP_NAMES:
            continue
        errors = check_file(path)
        if not errors:
            continue
        actions = fix_file(path, rel, errors, dry)
        if actions:
            fixed += 1
            print(f"{'[DRY] ' if dry else ''}{rel}: {'; '.join(actions)}")
    print(f"\n{'Would fix' if dry else 'Fixed'}: {fixed} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
