# Proactivity — Larry acts, doesn't just report

The dispatch layer (see [task-dispatch.md](task-dispatch.md)) lets any agent
pick up work from any channel. This doc covers the next step: making Larry
**generate** work instead of waiting for a human to dispatch it.

Three proactivity layers sit on top of dispatch:

```
    session-init / hook
             │
             ▼
    proactive_scanner.py    ── scans inbox, notify-queue, Gmail, failed
                               tasks → creates tasks directly via task_lib
                               (bounded, deduped, capped)

    nightly batch (bulk-tier model)
             │
             ▼
    batch3-morgonbrief      ── emits `proactive-trigger` events for
                               actionable "radar" points → dispatcher
                               creates tasks

    brains-bus events
             │
             ▼
    event_dispatcher.py     ── daemon subscribing on bus as brain
                               "dispatcher". Rules:
                                 • task-result(failed)      → self-diagnose
                                 • session-error            → self-triage
                                 • proactive-trigger        → pass-through
```

---

## Layer 1 — session-init scanner

`scripts/proactive_scanner.py` runs at session init (from the hook) and
dispatches tasks for anything actionable it finds:

| Source                     | Action                                           |
|----------------------------|--------------------------------------------------|
| `_private/notify-queue.json` photos unread | Barry sort                       |
| `_private/notify-queue.json` voices unread | Harry transcribe                 |
| `_private/notify-queue.json` messages w/ keywords | Route to matching agent   |
| `00-inbox/` files >24h old w/o `status:` | Larry triage                       |
| `_tasks/*/failed/` files <12h old | Larry diagnose                            |
| Gmail unread (via `gws`)   | Larry triage (never auto-reply)                  |

Dedup against today's already-dispatched titles; cap total dispatches
per run (default 10). The caps are important — a pathological queue should
never fan out into hundreds of tasks.

**Boundaries — what it NEVER does:**
- Send mail/messages
- Post to LinkedIn / external services
- Dispatch anything tagged as a decision or creative call
- Anything under `_private/` that's privacy 3/4 (only counts items, never
  quotes content)

Integrate into your session-init hook:

```bash
# in load-context.sh (or equivalent)
VAULT_ROOT="$PROJECT" python "$PROJECT/scripts/proactive_scanner.py" --cap 5
```

---

## Layer 2 — nightly brief dispatches

The nightly batch that produces the morning brief runs on the bulk model
tier (resolved via `simple_model()`, never a hardcoded name) and gets a new
final step: for each actionable "radar" point it identifies, post a
`proactive-trigger` event on the bus. The event-dispatcher daemon (layer 3)
picks it up and creates a task file, with dedup + rate limits. The morning
brief itself has since been hardened; see [finish-the-job.md](finish-the-job.md).

This keeps the prompt simple, the nightly batch doesn't need to know about
`task_lib`. It just posts a well-formed bus event:

```bash
python bus/brains-bus.py post \
  --from nightly --to dispatcher --kind proactive-trigger \
  --payload '{"agent":"barry","title":"Sort weekend photos",
              "description":"12 unsorted photos from 2026-04-19",
              "reason":"nightly brief 2026-04-20",
              "dedup":"nightly-photos-2026-04-20"}'
```

Max 5 triggers per nightly run. Creative / relational / external calls are
left to the human.

---

## Layer 3 — event-driven dispatcher

`scripts/event_dispatcher.py` is a long-running daemon that subscribes to the
bus as brain `dispatcher`. For every event it runs the rule registry.

Built-in rules:

| Event kind          | Rule                                                   |
|---------------------|--------------------------------------------------------|
| `task-result`       | If `success == False` → create larry-diagnose task     |
| `session-error`     | Create larry-triage task                               |
| `proactive-trigger` | Pass-through: dispatch to the agent in the payload     |

The pass-through rule is the proactivity hook: any script — a cron job, a
user-defined watcher, a webhook handler — can post a `proactive-trigger` and
get a properly-deduped, rate-limited task created without touching task_lib
directly.

**Anti-spam:**
- RAM-based dedup by key with 1h TTL (lost on restart, acceptable)
- Circuit breaker: 20 dispatches/hour max

**Guardian integration:** the daemon writes a PID file and heartbeat to
`<notifications-dir>/event-dispatcher.{pid,heartbeat}`. Your supervisor
restarts it when the heartbeat goes stale — same pattern as the task
watchers and bot listener.

---

## Why split these three layers?

They run at different cadences and handle different shapes of signal:

| Layer          | Cadence      | Signal shape                     |
|----------------|--------------|----------------------------------|
| session-init   | On-demand    | Point-in-time state of the vault |
| nightly brief  | Once per day | Curated "radar" from the bulk-tier model |
| bus dispatcher | Continuous   | Real-time events from agents     |

A single "do all the proactivity" module would have to poll everything
continuously, which wastes cycles and makes failures harder to localise.
Three small loops, each with a clear trigger, compose better — and each
layer can be disabled independently (delete the hook line, skip the nightly
step, stop the daemon) when you want to reduce noise.

---

## Layer 4 — Awareness mid-session

Layers 1-3 create work. Layer 4 makes the agent **aware** of what happened while it was busy: fresh bus events and fired reminders.

The first version did this in a `PreToolUse` hook that read the bus every 90 seconds and wrote what it found to stderr. None of it ever reached the model: a hook's stderr with exit code 0 is shown to nobody. Two things replaced it:

- **A Monitor at session init.** The session starts a background watch on the bus (the harness's Monitor tool or an equivalent tail) and is woken by new events instead of polling on every tool call.
- **Hook context the right way.** A hook that must reach the model writes JSON on stdout: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}`. `scripts/inject-context.py` now does only that, and only for one thing: a voice hint when the agent is about to write prose (`.md`, `.txt`), matched on the file path.

```
# .claude/settings.json
{
  "matcher": "Edit|Write",
  "hooks": [{ "type": "command", "command": "python hooks/inject-context.py" }]
}
```

Test a new hook by checking what the model actually receives, not by seeing the hook run. A hook that runs and reaches nobody looks exactly like one that works.

---

## Files

```
scripts/proactive_scanner.py    — session-init scanner (layer 1)
scripts/event_dispatcher.py     — bus-subscribing daemon (layer 3)
scripts/inject-context.py       — pre-turn context injection hook (layer 4)
docs/task-dispatch.md           — underlying dispatch infra (prereq)
```
