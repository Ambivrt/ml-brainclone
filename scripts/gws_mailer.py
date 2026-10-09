"""
gws_mailer.py -- shared outgoing-mail helper with mandatory local archiving.

All outgoing mail from the ecosystem should go through this module.
A markdown copy is written to `_private/sent-mail/YYYY-MM-DD_HHMMSS-<label>.md`
BEFORE the gws subprocess call -- so even if the send fails, the content is
preserved.

Rules:
  - The agent saves EVERYTHING, including sent mail.
  - The agent sends as itself (AGENT_SENDER), never as the owner.
  - The archive copy's privacy level follows the content, not the folder. It
    lives under _private/ whatever the level: the place says nothing about it.
  - One send per idempotency key (idempotency.py). Inside a task executor a key
    is derived automatically, so a rerun after a lost receipt never mails twice.
    A timeout counts as "maybe sent": the key stays pending and is not retried.

Attachments go as multipart/mixed, inline images as multipart/related with
`Content-ID: <filename>`; reference them in the HTML as `src="cid:<filename>"`.
A missing file sends nothing.

Requires: `gws` CLI (https://github.com/nicholasgasior/gws) authenticated.

Setup:
  export VAULT_PATH=/path/to/your/vault
  export AGENT_SENDER=agent@example.com
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import idempotency
except Exception:  # without it, mail is sent as before
    idempotency = None

VAULT = Path(os.environ.get("VAULT_PATH", "."))
SENT_MAIL_DIR = VAULT / "_private" / "sent-mail"
AGENT_SENDER = os.environ.get("AGENT_SENDER", "agent@example.com")
SKIPPED_DUPLICATE = "SKIPPED: already sent or started under the same idempotency key"

# A stand-in for a real content classifier. Replace with yours.
_PRIVATE_HINTS = re.compile(r"\b(health|diagnos|salary|password|relationship|therapy)\w*", re.I)


def mail_privacy(subject: str, body: str, attachments: Iterable[str | Path] = ()) -> int:
    """The mail's level from its content and attachment names. Unknown leans private."""
    text = f"{subject}\n{body}\n" + " ".join(str(a) for a in attachments)
    return 3 if _PRIVATE_HINTS.search(text) else 2


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
    sender: str = AGENT_SENDER,
    extra: dict | None = None,
    privacy: int | None = None,
) -> Path:
    """Save a markdown copy of an outgoing mail. Returns the file path."""
    if privacy is None:
        privacy = mail_privacy(subject, body)
    SENT_MAIL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = SENT_MAIL_DIR / f"{stamp}-{_safe_label(label)}.md"
    lines = [
        "---",
        "tags: [system/mail]",
        "status: done",
        f"created: {datetime.now().strftime('%Y-%m-%d')}",
        f"privacy: {privacy}",
        f"label: {label}",
        f"to: {to}",
        f"from: {sender}",
        f"subject: {subject}",
        f"sent_at: {datetime.now().isoformat(timespec='seconds')}",
    ]
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _claim(to: str, label: str, subject: str, key: str | None) -> tuple[str | None, bool]:
    """(key, run). The key is stored before the gws call. run=False: already sent or started."""
    if idempotency is None:
        return None, True
    try:
        key = key or idempotency.scoped_key("mail", to)
        if key is None:
            return None, True
        return key, idempotency.claim(key, kind="mail", meta={"to": to, "label": label, "subject": subject})
    except Exception:  # a broken key store must not stop mail
        return None, True


def _settle(key: str | None, outcome: str) -> None:
    """'sent' -> done, 'not_sent' -> released, 'unknown' -> stays pending."""
    if key is None or idempotency is None:
        return
    try:
        if outcome == "sent":
            idempotency.confirm(key)
        elif outcome == "not_sent":
            idempotency.release(key)
    except Exception:
        pass


def _mime(subject, html_body, plain_body, to, sender, files, inline_files):
    if html_body:
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(plain_body or subject, "plain", "utf-8"))
        body.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        body = MIMEText(plain_body or subject, "plain", "utf-8")
    if inline_files:
        related = MIMEMultipart("related")
        related.attach(body)
        for f in inline_files:
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            main, _, sub = ctype.partition("/")
            part = MIMEImage(f.read_bytes(), _subtype=sub) if main == "image" else MIMEApplication(f.read_bytes(), _subtype=sub)
            part.add_header("Content-ID", f"<{f.name}>")
            part.add_header("Content-Disposition", "inline", filename=("utf-8", "", f.name))
            related.attach(part)
        body = related
    if files:
        msg = MIMEMultipart("mixed")
        msg.attach(body)
        for f in files:
            ctype = "text/markdown" if f.suffix.lower() == ".md" else (mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            main, sub = ctype.split("/", 1)
            part = MIMEText(f.read_text(encoding="utf-8"), sub, "utf-8") if main == "text" else MIMEApplication(f.read_bytes(), _subtype=sub)
            part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", f.name))
            msg.attach(part)
    else:
        msg = body
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    return msg


def send_html_mail(
    subject: str,
    html_body: str,
    label: str,
    to: str,
    sender: str = AGENT_SENDER,
    plain_body: str = "",
    timeout: int = 60,
    extra_archive: dict | None = None,
    idempotency_key: str | None = None,
    attachments: Iterable[str | Path] | None = None,
    inline_images: Iterable[str | Path] | None = None,
    privacy: int | None = None,
) -> tuple[bool, str, Path]:
    """Send via gws CLI. Empty html_body sends plain text. Archives a copy first.

    Returns (ok, stdout_or_err, archive_path).
    """
    files = [Path(a) for a in (attachments or [])]
    inline_files = [Path(a) for a in (inline_images or [])]
    missing = [str(f) for f in (*files, *inline_files) if not f.is_file()]
    if missing:
        return False, f"Attachment missing: {', '.join(missing)}", Path()
    extra = dict(extra_archive or {})
    if files:
        extra["attachments"] = ", ".join(f.name for f in files)
    if inline_files:
        extra["inline_images"] = ", ".join(f.name for f in inline_files)
    text = html_body or plain_body
    if privacy is None:
        privacy = mail_privacy(subject, f"{html_body}\n{plain_body}", files)
    archive_body = text[:500] + "..." if len(text) > 500 else text

    key, run = _claim(to, label, subject, idempotency_key)
    if not run:
        dummy = archive_mail(label + "-SKIPPED-DUPLICATE", subject, archive_body, to=to, sender=sender, extra=extra, privacy=privacy)
        return True, SKIPPED_DUPLICATE, dummy
    archive_path = archive_mail(label, subject, archive_body, to=to, sender=sender, extra=extra, privacy=privacy)

    msg = _mime(subject, html_body, plain_body, to, sender, files, inline_files)
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    try:
        result = subprocess.run(
            ["gws", "gmail", "users", "messages", "send",
             "--params", json.dumps({"userId": "me"}),
             "--json", json.dumps({"raw": encoded}),
             "--format", "json"],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout, errors="replace",
        )
    except subprocess.TimeoutExpired:
        _settle(key, "unknown")      # may have gone out: never send it again
        return False, "gws timeout", archive_path
    except FileNotFoundError:
        _settle(key, "not_sent")
        return False, "gws CLI missing from PATH", archive_path
    except Exception as e:
        _settle(key, "unknown")
        return False, f"gws error: {e}", archive_path

    if result.returncode == 0:
        _settle(key, "sent")
        return True, (result.stdout or "").strip(), archive_path
    _settle(key, "not_sent")
    return False, (result.stderr or result.stdout or "").strip(), archive_path


def send_mail(
    subject: str,
    body: str,
    label: str,
    to: str,
    sender: str = AGENT_SENDER,
    timeout: int = 60,
    extra_archive: dict | None = None,
    idempotency_key: str | None = None,
    attachments: Iterable[str | Path] | None = None,
    privacy: int | None = None,
) -> tuple[bool, str, Path]:
    """Plain-text mail. Same archive, key and attachment rules as send_html_mail."""
    return send_html_mail(subject, "", label, to=to, sender=sender, plain_body=body, timeout=timeout,
                          extra_archive=extra_archive, idempotency_key=idempotency_key,
                          attachments=attachments, privacy=privacy)


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
