"""
gws_mailer.py — shared outgoing-mail helper with mandatory local archiving.

All outgoing mail from the Larry ecosystem should go through this module.
A markdown copy is written to `_private/sent-mail/YYYY-MM-DD_HHMMSS-<label>.md`
BEFORE the gws subprocess call — so even if the send fails, the content is
preserved.

Rule: the agent saves EVERYTHING, including sent mail.

Requires: `gws` CLI (https://github.com/nicholasgasior/gws) authenticated.

Setup:
  export VAULT_PATH=/path/to/your/vault
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

VAULT = Path(os.environ.get("VAULT_PATH", "."))
SENT_MAIL_DIR = VAULT / "_private" / "sent-mail"


def _safe_label(label: str) -> str:
    keep = []
    for ch in label.strip().lower():
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch in (" ", "/"):
            keep.append("-")
    cleaned = "".join(keep).strip("-") or "mail"
    return cleaned[:60]


def archive_mail(
    label: str,
    subject: str,
    body: str,
    to: str,
    sender: str,
    extra: dict | None = None,
) -> Path:
    """Save a markdown copy of an outgoing mail. Returns the file path."""
    SENT_MAIL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe = _safe_label(label)
    path = SENT_MAIL_DIR / f"{stamp}-{safe}.md"

    lines = [
        "---",
        "tags: [mail, sent, auto]",
        "status: active",
        f"created: {datetime.now().strftime('%Y-%m-%d')}",
        "privacy: 3",
        f"label: {label}",
        f"to: {to}",
        f"from: {sender}",
        f"subject: {subject}",
        f"sent_at: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if extra:
        for k, v in extra.items():
            lines.append(f"{k}: {v}")
    lines += ["---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def send_mail(
    subject: str,
    body: str,
    label: str,
    to: str,
    sender: str,
    content_type: str = "text/plain; charset=utf-8",
    timeout: int = 60,
    extra_archive: dict | None = None,
) -> tuple[bool, str, Path]:
    """Send mail via gws CLI. Archives a copy first.

    Returns (ok, stdout_or_err, archive_path).
    """
    archive_path = archive_mail(label, subject, body, to=to, sender=sender, extra=extra_archive)

    raw = (
        f"From: {sender}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
        f"{body}"
    )
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

    try:
        result = subprocess.run(
            [
                "gws", "gmail", "users", "messages", "send",
                "--params", json.dumps({"userId": "me"}),
                "--json", json.dumps({"raw": encoded}),
                "--format", "json",
            ],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout, errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "gws timeout", archive_path
    except FileNotFoundError:
        return False, "gws CLI missing from PATH", archive_path
    except Exception as e:
        return False, f"gws error: {e}", archive_path

    if result.returncode == 0:
        return True, (result.stdout or "").strip(), archive_path
    return False, (result.stderr or result.stdout or "").strip(), archive_path


def archive_raw_send(label: str, args: Iterable[str]) -> Path | None:
    """Pull mail content out of a raw `gws gmail ... send` invocation and archive it.

    Used by pass-through wrappers (such as bot tool-call handlers) where the
    caller passes the gws argv directly instead of using send_mail().
    Returns the archive path if extraction succeeded.
    """
    args = list(args)
    try:
        if "--json" not in args:
            return None
        idx = args.index("--json")
        if idx + 1 >= len(args):
            return None
        payload = json.loads(args[idx + 1])
        raw_b64 = payload.get("raw")
        if not raw_b64:
            return None
        raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        if "\r\n\r\n" in raw_text:
            headers, body = raw_text.split("\r\n\r\n", 1)
        elif "\n\n" in raw_text:
            headers, body = raw_text.split("\n\n", 1)
        else:
            headers, body = raw_text, ""
        subject = ""
        to = ""
        sender = ""
        for line in headers.splitlines():
            low = line.lower()
            if low.startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
            elif low.startswith("to:"):
                to = line.split(":", 1)[1].strip()
            elif low.startswith("from:"):
                sender = line.split(":", 1)[1].strip()
        return archive_mail(label, subject or "(no subject)", body, to=to, sender=sender)
    except Exception:
        return None
