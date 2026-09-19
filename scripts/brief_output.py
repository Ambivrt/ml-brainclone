"""brief_output.py -- shared write helper for the morning brief.

Both the batch runner (scripts/nightly-runner.sh, via the CLI mode at the
bottom of this file) and any daemon that composes the brief directly (e.g. a
Darry-style sleep-cycle service, via import) write the brief through this
module instead of letting the Claude session write the file itself.

Why: the session that compiles the brief has read-only tools (Read/Glob/Grep),
no Bash, Write or Edit -- see docs/security-untrusted-input.md. It answers
with the brief text on stdout, and that text lands on disk HERE, after
validation. This is what makes the tool restriction meaningful: a session
with no Write tool cannot be tricked into using one, and a session that could
still write the file itself would defeat the point of restricting it.

Validation (write_brief_atomic):
  - the text must not be empty or unreasonably short (min_length characters)
  - the text must start with front matter (---\\n...\\n---)

If validation fails, the target path is left UNTOUCHED and nothing is
written. A broken or empty session response must never delete a previously
valid brief -- yesterday's brief beats no brief or a corrupt one.

The write itself is atomic (temp file in the same directory + os.replace),
so a reader (a quality gate that runs right after, or the next session that
reads the brief) never sees a partially written file.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MIN_LENGTH = 200
_FRONT_MATTER_RE = re.compile(r"^---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


def validate_brief_text(text: str | None, min_length: int = MIN_LENGTH) -> tuple[bool, str]:
    """Validate brief text. Returns (ok, reason-if-not-ok)."""
    if text is None:
        return False, "no text"
    stripped = text.lstrip("﻿").lstrip("\n")
    if not stripped.strip():
        return False, "empty text"
    if len(stripped) < min_length:
        return False, f"unreasonably short ({len(stripped)} chars, {min_length} required)"
    if not _FRONT_MATTER_RE.match(stripped):
        return False, "missing front matter (---...---) at the start of the text"
    return True, ""


def write_brief_atomic(target_path: Path, text: str | None,
                        min_length: int = MIN_LENGTH) -> tuple[bool, str]:
    """Validate and atomically write to target_path.

    On validation failure: target_path is left completely UNCHANGED (the
    previous version is kept). Returns (wrote, reason-if-not-written)."""
    target_path = Path(target_path)
    ok, reason = validate_brief_text(text, min_length=min_length)
    if not ok:
        return False, reason

    content = text.lstrip("﻿").lstrip("\n")
    if not content.endswith("\n"):
        content += "\n"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp-{os.getpid()}")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return True, ""


def _main(argv: list[str]) -> int:
    """CLI mode: python brief_output.py <source-file-with-brief-text> <target-file>

    Used by nightly-runner.sh (bash), which cannot import the module
    directly. The source file is the session's raw stdout, captured to a
    file by the caller."""
    if len(argv) != 3:
        print("Usage: brief_output.py <source-file-with-brief-text> <target-file>",
              file=sys.stderr)
        return 2
    src_path, dst_path = Path(argv[1]), Path(argv[2])
    try:
        text = src_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"Could not read source file {src_path}: {exc}", file=sys.stderr)
        return 1

    wrote, reason = write_brief_atomic(dst_path, text)
    if wrote:
        print(f"Brief written: {dst_path}")
        return 0
    print(f"Validation failed, previous file kept ({dst_path}): {reason}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
