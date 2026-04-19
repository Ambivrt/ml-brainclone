# Logging Architecture — Save Everything

Core rule: the second brain must save every input AND every agent reply as
text. No silent drops. If a pipeline fails, the local archive still has the
data — the agent can rebuild state from disk.

This document describes the shared modules that enforce that rule across
Larry, Barry, Harry, Parry, and the nightly batch jobs.

---

## Where everything lands

| File | Contents | Writers |
|------|----------|---------|
| `_private/live-transcript-log.md` | All voice + text turns (user + agent), fulltext | `harry_logger.py` (all Harry scripts) |
| `_private/telegram/YYYY-MM-DD.md` | All Telegram turns (day-per-file) | Telegram bot listener |
| `_private/mood-log.md` | Mood + 60-char preview of each turn | Harry STT scripts |
| `_private/sent-mail/YYYY-MM-DD_HHMMSS-<label>.md` | Copy of every outgoing mail | `gws_mailer.py` + `_archive_sent_mail` shell helper |
| `_private/brains-bus.db` | SQLite WAL — every inter-agent event with full JSON payload, no retention | brains-bus |
| `03-projects/barry/audit-log.jsonl` | One JSONL row per Barry event (generation, qa, upscale, api-complete) | `barry_audit.py` |
| `03-projects/ml-brainclone/notifications/parry-guardian.log` | Parry verdicts + exception tracebacks | Parry guardian |
| `03-projects/ml-brainclone/operations/nattskift/logs/` | One log per nightly batch run | `nattskift-runner.sh` |
| `00-inbox/morgonbrief-YYYY-MM-DD.md` | Generated morning brief before mail | Nightly batch |

All archives live in the vault under `_private/` (privacy level 3–4) or in
the project-specific operations folder.

---

## Shared modules (scripts/)

### `harry_logger.py`
Transcript logger for every Harry script (voice, STT, TTS, MCP server,
listen, greet). One function to import:

```python
from harry_logger import log_transcript, log_session_header

log_session_header("harry-voice")
log_transcript("User", transcript, "harry-voice")
log_transcript("Harry", reply_text, "harry-voice")
```

Writes to `$VAULT_PATH/_private/live-transcript-log.md`.

### `barry_audit.py`
Unified event log for Barry. One call per event:

```python
from barry_audit import append_audit

append_audit("generation", filename="barry-00042.png", category="sfw/portrait", ...)
append_audit("qa",         filename="barry-00042.png", pass_=True, score=8, ...)
append_audit("upscale",    filename="barry-00042.png", scale=2, cost_usd=0.02)
append_audit("api-complete", model="chroma", cost_usd=0.0, ...)
```

Writes to `$VAULT_PATH/03-projects/barry/audit-log.jsonl`.

### `gws_mailer.py`
Outgoing-mail helper that archives BEFORE sending. Any script that sends
mail should use this rather than calling `gws` directly:

```python
from gws_mailer import send_mail

ok, msg, archive_path = send_mail(
    subject="Morning brief",
    body=brief_text,
    label="morgonbrief",
    to="you@example.com",
    sender="you@example.com",
)
```

For pass-through wrappers that don't control the call site (e.g. a bot
tool-handler that forwards arbitrary gws argv), use `archive_raw_send` to
extract the mail content from the raw argv and archive it before the
subprocess runs.

---

## Shell helper pattern

Nightly batch scripts that send mail via `gws` directly use the same
pattern inline:

```bash
_archive_sent_mail() {
    local label="$1"
    local content="$2"
    local archive_dir="$VAULT/_private/sent-mail"
    mkdir -p "$archive_dir"
    local stamp
    stamp=$(date +%Y-%m-%d_%H%M%S)
    local archive_file="$archive_dir/${stamp}-${label}.md"
    {
        echo "---"
        echo "tags: [mail, sent, auto]"
        echo "status: active"
        echo "created: $(date +%Y-%m-%d)"
        echo "privacy: 3"
        echo "label: $label"
        echo "sent_at: $(date -Iseconds)"
        echo "---"
        echo
        echo "$content"
    } > "$archive_file"
}
```

Call it with the body text BEFORE `gws gmail users messages send`.

---

## Parry logging

`parry_guardian.py` writes every verdict and exception (with full traceback)
to `notifications/parry-guardian.log` via a small `_log()` helper that also
echoes to stdout. Exceptions are caught at the event-loop boundary and the
traceback is logged — so a guardian crash is diagnosable without scrolling
through the Task Scheduler log.

```python
LOG_FILE = VAULT / "03-projects" / "ml-brainclone" / "notifications" / "parry-guardian.log"

def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)
```

---

## Privacy

All logs are privacy level 3–4 (`_private/` or project-internal). Never
cite or summarize their contents in output that could leave the vault. The
vault itself is synced via a private Git repository.

---

## Known gaps

- **MCP tool calls (mempalace and similar)** — call + return pairs are not
  logged in a dedicated file. Claude Code already saves the full session
  transcript under `.claude/projects/`, which covers this.
- **Ad-hoc mail from arbitrary scripts** — any new script that sends mail
  MUST route through `gws_mailer.send_mail()` or call
  `_archive_sent_mail` from shell. Greps for `gws gmail ... send` are part
  of the nightly hygiene pass.
