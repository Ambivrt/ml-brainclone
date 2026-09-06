# Tarry Setup — Temporal Orchestrator

Tarry is Larry's time-keeping daemon. It handles everything time-bound that Larry cannot hold in active context between sessions.

- **Larry** — thinks, plans, orchestrates
- **Barry** — sees (images)
- **Harry** — hears and speaks (audio)
- **Parry** — guards, filters, judges
- **Tarry** — remembers when
- **Farry** — understands all languages

---

## What Tarry Does

| Domain | Function |
|--------|----------|
| Reminders | Fires at a specified time via Telegram + session injection |
| Follow-ups | Tracks open threads and nudges Larry when they go stale |
| Recurring tasks | Registers repeating jobs (daily, weekly, custom interval) |
| Interrupted session recovery | Detects sessions that ended mid-task and re-queues the work |

Tarry does not execute tasks itself — it writes to the queue and relies on Larry (and the brains-bus) to deliver notifications when the time comes.

---

## Architecture

Tarry is a **daemon**, like Parry. It runs as a long-lived background process and polls its queue every 30 seconds.

```
tarry_service.py (daemon, pythonw)
        │
        │ polls every 30s
        ▼
_private/tarry-queue.json
        │
        │ on trigger time reached:
        ▼
brains-bus  →  Larry receives task-result event
        │
        ▼
Telegram notification + session injection
```

Queue categories:

| Key | Purpose |
|-----|---------|
| `reminders` | One-shot time-based reminders |
| `follow_ups` | Open threads to check back on |
| `recurring` | Repeating scheduled tasks |
| `interrupted` | Sessions that ended without completing a task |

---

## Quick Start

```bash
# Start Tarry manually (stays in terminal)
python 03-projects/tarry/tarry_service.py

# Start Tarry in background (Windows)
pythonw 03-projects/tarry/tarry_service.py

# Check status
python 03-projects/tarry/tarry_service.py --status
```

---

## Installation

1. Copy `tarry_service.py` to `03-projects/tarry/tarry_service.py` in your vault.
2. Create the queue file on first run (Tarry initializes it automatically if missing):

```json
{
  "reminders": [],
  "follow_ups": [],
  "recurring": [],
  "interrupted": []
}
```

3. Register the Windows Task Scheduler autostart (see below).

---

## Windows Task Scheduler Autostart

Tarry should start automatically when you log in, like Parry. The start script follows the [daemon-stability patterns](daemon-stability.md): liveness check after launch, stderr-only redirect, singleton guard, and `pythonw` for windowless operation.

```powershell
# Register Tarry as a scheduled task (run once at setup)
powershell -File 03-projects/tarry/startup/tarry-start.ps1
```

The `tarry-start.ps1` script should:
1. Check for an existing PID file (singleton guard)
2. Launch with `pythonw.exe` (no console window)
3. Redirect only stderr (let Python handle its own logging)
4. Wait 800ms and verify the process is still alive (liveness check)
5. Write the PID file on success

See [daemon-stability.md](daemon-stability.md) for the full start script template.

Or register manually:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "pythonw.exe" `
    -Argument "{{VAULT_PATH}}\03-projects\tarry\tarry_service.py" `
    -WorkingDirectory "{{VAULT_PATH}}"

$trigger = New-ScheduledTaskTrigger -AtLogon

Register-ScheduledTask `
    -TaskName "Larry Tarry" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest `
    -Force
```

---

## Queue File

**Path:** `_private/tarry-queue.json`

This file is privacy L3 — do not commit it to a public repo.

### Reminder schema

```json
{
  "id": "rem-20260422143000",
  "created": "2026-04-22T14:30:00",
  "created_by": "larry",
  "what": "Follow up with Emma about the Coop proposal",
  "when": "2026-04-23T09:00:00",
  "channels": ["telegram", "session"],
  "status": "pending",
  "context": "She should have replied by now"
}
```

### Status values

| Status | Meaning |
|--------|---------|
| `pending` | Scheduled, not yet fired |
| `fired` | Notification sent |
| `dismissed` | Acknowledged by user |
| `snoozed` | Postponed (has `snoozed_until`) |

---

## Bus Integration

Tarry communicates via the brains-bus (brain name: `tarry`).

```bash
# Post a reminder directly over the bus
python 03-projects/ml-brainclone/bus/brains-bus.py post \
    --from larry \
    --to tarry \
    --kind reminder-request \
    --payload '{"what":"Review the proposal draft","when":"2026-04-23T10:00","channels":["telegram"]}'

# Read Tarry status
python 03-projects/ml-brainclone/bus/brains-bus.py read --brain tarry
```

When a reminder fires, Tarry posts a `task-result` event back to Larry on the bus, which triggers a Telegram push and injects context into the next session.

---

## Status Check

Tarry writes a heartbeat file while running:

```
_private/.notifications/tarry-service.heartbeat
```

The heartbeat is updated every 15 seconds. If it goes stale (>2 min), the Task Scheduler restarts the process.

```powershell
# Check Tarry heartbeat
powershell -File 03-projects/tarry/startup/tarry-status.ps1
```

---

## Dispatching Tarry Tasks via task_lib

Larry can schedule a reminder by dispatching a task to the `tarry` agent:

```python
from scripts.task_lib import create_task

create_task(
    "tarry",
    title="Remind me: follow up on Coop proposal",
    description="2026-04-23T09:00:00",  # ISO datetime in description
    from_source="larry-session",
    priority="normal",
)
```

The `agent_task_watcher` picks this up and appends it to `tarry-queue.json`.

---

## Release Chain Pattern

A release chain is a pre-scheduled cascade of reminders tied to a project milestone (album release, product launch, event). Instead of creating reminders one at a time, you build the full chain in advance and let Tarry fire them on schedule.

### When to use

- Product/content launches with a fixed date and known preparation steps
- Multi-week campaigns where each week has different tasks
- Anything with a countdown where missing a step derails the timeline

### Structure

```json
{
  "reminders": [
    {
      "id": "launch-content-brief-w1",
      "created": "2026-04-26T22:00:00",
      "fire_at": "2026-04-27T09:00:00",
      "status": "waiting",
      "message": "Content brief week 1. LinkedIn post Monday, playlist curation Tuesday.",
      "context": "See content-calendar.md for details."
    },
    {
      "id": "launch-verify-minus3",
      "created": "2026-04-26T22:00:00",
      "fire_at": "2026-05-21T08:00:00",
      "status": "waiting",
      "message": "VERIFICATION (-3d): All metadata correct? Assets uploaded? Links working?",
      "context": "Last chance to fix issues before launch."
    },
    {
      "id": "launch-day",
      "created": "2026-04-26T22:00:00",
      "fire_at": "2026-05-24T07:00:00",
      "status": "waiting",
      "message": "LAUNCH DAY. Run full checklist.",
      "context": "See launch-spec.md section 5.3."
    }
  ],
  "recurring": [
    {
      "id": "launch-weekly-report",
      "created": "2026-04-26T22:00:00",
      "schedule": "every friday 08:00",
      "message": "Weekly metrics report — collect data, deliver in daily note.",
      "context": "Report format in launch-spec.md section 5.2."
    }
  ]
}
```

### Key fields

| Field | Purpose |
|-------|---------|
| `fire_at` | ISO datetime — when Tarry fires this reminder |
| `context` | Pointer to the spec/doc with full details (keeps the reminder short) |
| `include_in_brief` | Optional. Path to a file that should be injected into the next morning brief email (e.g., a pre-written post ready to copy-paste) |

### Building a chain

1. Define the milestone date (T-0)
2. Work backwards: what must happen at T-3, T-7, T-14, T-21?
3. Add weekly recurring tasks (reports, content briefs)
4. Add verification checkpoints near T-0
5. Write all reminders in one batch — Larry generates the full JSON

### Lifecycle

```
waiting → fired → acknowledged
              ↘ snoozed → fired (again)
```

Reminders stay `waiting` until `fire_at` passes. Tarry fires them into the morning brief / Telegram / session. Larry marks them `acknowledged` after the user sees them. Recurring reminders re-queue automatically.

### Content calendar integration

A release chain pairs naturally with a vault-based content calendar (`content-calendar.md`). The calendar holds the full plan (dates, channels, topics, status). Tarry reminders point into it via `context`, keeping reminders lightweight.

---

## See Also

- [daemon-stability.md](daemon-stability.md) -- Daemon stability patterns (start scripts, heartbeats, circuit breakers)
- [parry-setup.md](parry-setup.md) -- Parry daemon (same process model)
- [brains-bus-setup.md](brains-bus-setup.md) -- Inter-agent event bus
- [task-dispatch.md](task-dispatch.md) -- Task queue system
- [architecture-overview.md](architecture-overview.md) -- Agent ecosystem overview
