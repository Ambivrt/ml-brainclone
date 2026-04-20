# Task Dispatch — Inter-Agent Work Queue

Give Larry/Harry/Barry/Parry the ability to pick up jobs from anywhere — Telegram, mail, a CLI — and execute them on their own station, asynchronously.

The problem: the Telegram listener could log a request ("Harry, fix the bug in X"), but nothing was wired to act on it. Work piled up in the vault and only moved when the user was at the keyboard.

The solution: a **file-primary, bus-secondary** dispatch layer where the inbox doubles as the queue and each agent owns its own watcher process.

---

## Architecture

```
    Telegram / mail / CLI
             │
             ▼
    +-----------------+
    |  Larry listener |   (Claude tool: dispatch_task)
    +-----------------+
             │   writes
             ▼
    00-inbox/task-{agent}-{ts}-{slug}-{id}.md   ← the queue
             │   frontmatter: agent: <name>, status: pending
             │
     one watcher per agent, each polling only its own prefix
             │
             ▼  atomic rename (NTFS os.replace)
    _tasks/{agent}/processing/…md
             │   executor runs
             ▼
    _tasks/{agent}/{done|failed}/…md            ← audit trail
             │
             ▼  bus: task-result event → to=larry
    Listener subscriber → Telegram notification
```

Three invariants make this safe:

1. **Filesystem is source of truth.** If the bus DB corrupts, the task files are still readable by a human and can be replayed.
2. **Atomic claim via `os.replace`** — two watchers cannot process the same task even in a race.
3. **Bus is notification-only** — the final result event is what pages the user. Tasks themselves never depend on the bus being up.

---

## File layout

```
<vault>/
├── 00-inbox/
│   └── task-larry-20260420-100034-smoke-test-0abc1234.md   ← pending
├── _tasks/
│   ├── larry/
│   │   ├── processing/
│   │   ├── done/
│   │   └── failed/
│   ├── harry/
│   ├── barry/
│   └── parry/
```

Task filename encodes the agent as the second segment so watchers can skim filenames without reading frontmatter:

```
task-{agent}-{YYYYMMDD-HHMMSS}-{slug}-{8-char-id}.md
```

## Task file format

```markdown
---
tags: [task, agent/harry]
task_id: 0abc1234
agent: harry
status: pending          # pending | processing | done | failed
priority: normal         # low | normal | high
from_source: telegram
created: 2026-04-20T10:00:34
privacy: 2
---

# Fix race in larry_bot_listener

## Beskrivning
The watchdog kills the listener when milla_search hangs on a
ChromaDB lock. Wrap it in a ThreadPoolExecutor with 15s timeout
and add a background heartbeat thread.
```

When a watcher claims the task, the frontmatter gains `status: processing` and `claimed_at`. On completion, `status`, `completed_at`, plus a **Resultat** block is appended with the executor's summary and, on failure, the full error.

---

## Executor registry

Each agent has its own executor function. The watcher is one script that loads the right executor based on `--agent`:

| Agent | Executor | Typical work |
|-------|----------|--------------|
| `larry` | `claude -p <prompt>` in vault root | Vault edits, memory updates, planning |
| `harry` | `claude -p <prompt>` in `03-projects/harry/` | Code patches, audio jobs, system work |
| `barry` | `python 03-projects/barry/barry.py <prompt>` | Image generation |
| `parry` | Direct (no subprocess) | Gatekeeper verdicts |

Adding a new agent is a three-line change: add its executor function to the registry in `agent_task_watcher.py`, add the name to `MANAGED_TASK_AGENTS` in `parry_service.py`, restart the guardian.

---

## Listener tool: `dispatch_task`

The Telegram listener gets a Claude tool:

```json
{
  "name": "dispatch_task",
  "description": "Dispatch a task to another agent. Use when user asks for actual execution (fix bug, generate image, run analysis), not just a chat answer.",
  "input_schema": {
    "properties": {
      "agent":       {"enum": ["larry", "harry", "barry", "parry"]},
      "title":       {"type": "string"},
      "description": {"type": "string"},
      "priority":    {"enum": ["low", "normal", "high"]}
    },
    "required": ["agent", "title", "description"]
  }
}
```

Claude decides at inference time whether a Telegram message warrants a dispatch. Chit-chat and questions are answered inline. Work is dispatched. The user gets an acknowledgement in Telegram immediately, then a second notification when the task completes.

---

## Watcher lifecycle

Each watcher is a supervised process. On every poll (5s default):

1. `list_pending_for_agent(agent)` — glob `00-inbox/task-{agent}-*.md`, filter by frontmatter.
2. For each pending task: `claim_task()` via atomic rename to `_tasks/{agent}/processing/`.
3. Execute via the agent's executor function (subprocess with timeout).
4. `complete_task()` moves to `done/` or `failed/`, appends results to the file.
5. Emit `task-result` on the bus with `to="larry"` so the listener subscriber picks it up.

Heartbeats are written every 15s to `notifications/task-watcher-{agent}.heartbeat`. The Parry guardian restarts any watcher whose heartbeat goes stale (>60s) — the same pattern used for the listener and queue worker.

---

## Guardian integration

The Parry guardian (`bus/parry_service.py`) now manages three process classes:

- Bot listener
- Queue worker
- Task watchers (one per name in `MANAGED_TASK_AGENTS`)

On each watchdog tick (30s), it checks each process's PID file and heartbeat. If either is missing or stale, it respawns with the agent's runtime executable.

---

## Notification loop

The listener runs a background subscriber thread that polls the bus for `task-result` events addressed to `larry`. Each event becomes a Telegram message:

```
✅ Harry klar: Fix race in larry_bot_listener
Wrapped milla_search in ThreadPoolExecutor with 15s timeout
and added a background heartbeat thread. Listener verified
stable across 3 voice messages.
```

Failures include the last chunk of stderr. The user can react with an emoji to mark it resolved or ask a follow-up.

---

## Why this shape

**Filesystem-primary, not bus-primary.**  
The inbox is already the shared "working area" the user understands. Tasks as markdown files are greppable, diffable, human-readable, and survive DB corruption. Using the bus as the primary queue would make the whole chain fragile on SQLite hiccups.

**One watcher per agent, not a central dispatcher.**  
A central dispatcher is a single point of failure and a bottleneck. With per-agent watchers, Barry can be down while Larry and Harry keep running — and the tasks for Barry simply wait in the inbox until Barry comes back.

**Atomic rename for claim.**  
`os.replace` is atomic on NTFS (and on POSIX). Two watchers racing for the same file will have exactly one succeed and one get a `FileNotFoundError`. No lock files, no coordination, no lost work.

**Bus only for the callback.**  
The notification back to the user is where async messaging genuinely helps — the user isn't watching the filesystem. The bus also gives Parry a chance to veto anomalous results before they reach the user.

---

## Files

```
agents/task_lib.py              — create/claim/complete + frontmatter mutation
agents/agent_task_watcher.py    — universal watcher (run with --agent <name>)
bus/parry_service.py            — guardian; manages MANAGED_TASK_AGENTS
notifications/larry_bot_listener.py
                                — dispatch_task tool + result subscriber thread
```

See the reference implementations in `scripts/task_lib.py` and `scripts/agent_task_watcher.py`.
