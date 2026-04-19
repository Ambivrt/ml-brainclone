"""
barry_audit.py — unified JSONL audit-log for Barry (image agent).

One line per event (generation, qa, upscale, api-complete) to `audit-log.jsonl`.
Complement to the human-readable visual-index markdown notes and the
brains-bus event stream. This file is the long-term searchable archive of
the full Barry activity.

Rule: the agent saves EVERYTHING. No silent drops.

Setup:
  export VAULT_PATH=/path/to/your/vault
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

VAULT = Path(os.environ.get("VAULT_PATH", "."))
AUDIT_LOG = VAULT / "03-projects" / "barry" / "audit-log.jsonl"


def append_audit(event: str, **fields: Any) -> None:
    """Write one JSONL row. Silent on write-error — audit must never crash pipeline."""
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event}
    entry.update(fields)
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
