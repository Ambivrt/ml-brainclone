# Darry Setup — Sleep-Cycle Nightly Processor

Darry is Larry's nightly processing daemon. It replaces a flat batch-runner pattern with a biologically inspired sleep-cycle architecture: three phases that adapt to what actually needs doing each night.

- **Larry** — thinks, plans, orchestrates
- **Barry** — sees (images)
- **Harry** — hears and speaks (audio)
- **Parry** — guards, filters, judges
- **Tarry** — remembers when
- **Farry** — understands all languages
- **Darry** — dreams while you sleep

---

## What Darry Does

| Domain | Function |
|--------|----------|
| Light Sleep | Fast maintenance — cleanup, triage, health checks. Runs every night |
| Deep Sleep | Heavy processing — memory consolidation, indexing, knowledge distillation. Conditional |
| REM Sleep | Creative — cross-domain patterns, insights, project synthesis. Rare |
| Morning Brief | Single unified report summarizing the night's work |

Darry owns the night. From the moment the user goes to sleep until the morning brief is delivered, Darry orchestrates all nightly work. It does not execute tasks in other agents' domains — it dispatches to them (Milla for indexing, Carry for delivery, Parry for oversight).

---

## Sleep Phases

### Phase 1 — Light Sleep (every night)

**Purpose:** Fast maintenance. Clean, sort, triage. Cheap and quick.

**Model:** Haiku (batch-cheap, fast)

**Default schedule:** 22:00 - 00:00

| Job | Description |
|-----|-------------|
| Vault hygiene | Frontmatter audit, broken links, orphans, tag consistency, privacy check |
| Inbox triage | Sort inbox — what goes where? Suggest moves, flag stale items |
| Heartbeat check | All daemons healthy? Parry, Tarry, Carry, bot-listener |
| Queue cleanup | Clear acknowledged reminders, completed jobs |
| Tmp cleanup | Temporary files, abandoned drafts |
| Git status | Uncommitted changes? Stale branches? Large files that should not be tracked? |

**Output:** `00-inbox/nattrapport-light-YYYY-MM-DD.md` — short, bullet-format, actionable.

**Trigger:** Unconditional. Light Sleep runs every night.

---

### Phase 2 — Deep Sleep (conditional)

**Purpose:** Heavy processing. Consolidate memories, build structures, repair. GPU-intensive.

**Model:** Sonnet (stronger reasoning) + GPU (embedding indexing)

**Default schedule:** 00:00 - 04:00

| Job | Description | Condition |
|-----|-------------|-----------|
| Memory indexing | Incremental indexing of new/changed vault files | Always (skip if <5 changes) |
| KG hygiene | Stale triples, orphan entities, missing relations, conflicting facts | Every 3rd night OR >10 KG changes since last run |
| Knowledge distillation | Inbox notes older than N days promoted to structured knowledge notes | >5 notes in inbox older than 3 days |
| Diary compression | Summarize older diary entries, preserve the core | >50 unsummarized entries |
| Archive sweep | Inactive projects (>30d) flagged for archival | Every 7th night |
| FTS rebuild | Full-text search index rebuild | Every 7th night OR >50 file changes |
| Feedback audit | Cross-reference feedback rules vs. nattrapport violations, update tracker, generate Hot 10 | Always. See [feedback-loop.md](feedback-loop.md) |

**Adaptive logic:** Deep Sleep has conditions. If no condition is met, the phase is skipped entirely. The night does not need to be long if nothing heavy needs doing.

**Output:** `00-inbox/nattrapport-deep-YYYY-MM-DD.md` — detailed, with diff summary and stats.

---

### Phase 3 — REM Sleep (rare)

**Purpose:** Dream. Find patterns. Create connections no one explicitly asked for. Generate insights.

**Model:** Opus (creative, deep, associative)

**Default schedule:** 04:00 - 06:00

**Frequency:** 1-2 times per week, or triggered by specific events.

**Triggers:**

| Trigger | Description |
|---------|-------------|
| Time gap | More than 7 days since last REM |
| High activity day | Significant personal or project activity detected |
| Project milestone | Major release, deadline hit, or phase completion |
| Manual request | User explicitly asks for dream-mode analysis on a topic |
| Procrastination signal | Another agent flags multiple deferred items |

**Jobs:**

| Job | Description |
|-----|-------------|
| Cross-domain connections | What links project A to project B? Patterns in user decisions? |
| Creative suggestions | Thematic patterns in recent work that could inform new direction |
| Relationship mapping | Which contacts appeared frequently? Which disappeared? Why? |
| Project synthesis | Overlapping goals in separate projects — should they merge? |
| Health patterns | Activity + habits data trending negatively? Flag it |
| Sentiment drift | Tone in vault notes over time — trending happier? More stressed? |

**Output:** `00-inbox/nattrapport-rem-YYYY-MM-DD.md` — essay format, not bullets. Reflective, not instructive. Asks questions rather than giving answers.

**Privacy rule:** REM output is always privacy 2+ (personal). REM touching sensitive material should be privacy 3.

**Design principle:** REM observes patterns and asks questions. It never diagnoses, prescribes, or assumes intent. "I see X" — not "you have Y."

---

## Morning Brief

Darry's most important output. A single unified report replacing multiple scattered batch reports.

**Structure:**

```markdown
# Morning Brief — YYYY-MM-DD

## Urgent
- [Critical findings that need immediate attention]

## Vault
- [Hygiene results, inbox triage summary, counters]

## Memory
- [Indexing stats, KG updates, stale data cleaned]

## Dreams (REM)
> [Essay-style reflection — only present if REM ran]
> [Pattern observations, questions, gentle nudges]

## Today
- [Scheduled reminders from Tarry]
- [Pending items from Carry]
- [Deferred items flagged by other agents]
```

The morning brief is compiled from all phases that ran. If only Light Sleep ran, the brief is short. If REM ran, the dreams section is appended. If nothing needed doing, the brief says so.

**Delivery:** Darry compiles the brief, then hands it to the delivery agent (Carry or equivalent) for email + vault storage.

---

## Architecture

### Daemon — `darry_service.py`

```
darry_service.py
  |-- Configuration: darry-config.json (times, conditions, REM triggers)
  |-- Heartbeat: notifications/darry.heartbeat
  |-- PID: notifications/darry.pid
  |-- Log: notifications/darry.log
  |
  |-- schedule_tonight()
  |     Evaluate conditions -> decide which phases run
  |
  |-- run_light_sleep()
  |     claude --print --model haiku < prompts/light-sleep.md
  |
  |-- run_deep_sleep()
  |     claude --print --model sonnet < prompts/deep-sleep.md
  |     python -m mempalace mine (GPU)
  |
  |-- run_rem_sleep()
  |     claude --print --model opus < prompts/rem-sleep.md
  |
  |-- compile_morgonbrief()
  |     Summarize all phase outputs
  |     Render to HTML + markdown
  |     Hand to delivery agent
  |
  |-- cleanup()
        Archive night reports -> 06-archive/nattskift/YYYY-MM-DD/
```

---

## Configuration

**Path:** `03-projects/darry/darry-config.json`

```json
{
  "schedule": {
    "light_sleep_start": "22:00",
    "deep_sleep_start": "00:00",
    "rem_sleep_start": "04:00",
    "morgonbrief_deadline": "05:30",
    "quiet_hours_end": "06:00"
  },
  "deep_sleep_conditions": {
    "min_vault_changes": 5,
    "kg_changes_threshold": 10,
    "inbox_age_days": 3,
    "diary_compression_threshold": 50,
    "archive_sweep_interval_days": 7,
    "fts5_rebuild_interval_days": 7
  },
  "rem_triggers": {
    "max_days_between_rem": 7,
    "high_activity_today": false,
    "project_milestone": false,
    "procrastination_items_threshold": 3,
    "manual_request": null
  },
  "models": {
    "light": "haiku",
    "deep": "sonnet",
    "rem": "opus"
  }
}
```

All times are local. Conditions are evaluated at the start of each phase — if conditions change mid-night (e.g., Light Sleep discovers many issues), Deep Sleep may activate even if it was initially skipped.

---

## Quick Start

```bash
# Start Darry manually (stays in terminal)
python 03-projects/darry/darry_service.py

# Start Darry in background (Windows)
pythonw 03-projects/darry/darry_service.py

# Check status
python 03-projects/darry/darry_service.py --status

# Force a specific phase (useful for testing)
python 03-projects/darry/darry_service.py --phase light
python 03-projects/darry/darry_service.py --phase deep
python 03-projects/darry/darry_service.py --phase rem
```

---

## Installation

1. Copy `darry_service.py` to `03-projects/darry/darry_service.py` in your vault.
2. Copy `darry-config.json` to `03-projects/darry/darry-config.json` and adjust schedule/thresholds to your needs.
3. Create prompt templates in `03-projects/darry/prompts/`:
   - `light-sleep.md` — instructions for the Light Sleep phase
   - `deep-sleep.md` — instructions for the Deep Sleep phase
   - `rem-sleep.md` — instructions for the REM Sleep phase
4. Register the Windows Task Scheduler autostart (see below).

---

## Windows Task Scheduler Autostart

Darry should start automatically when you log in, like Parry and Tarry.

```powershell
# Register Darry as a scheduled task (run once at setup)
powershell -File 03-projects/darry/startup/darry-start.ps1
```

Or register manually:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "pythonw.exe" `
    -Argument "D:\path\to\vault\03-projects\darry\darry_service.py" `
    -WorkingDirectory "D:\path\to\vault"

$trigger = New-ScheduledTaskTrigger -AtLogon

Register-ScheduledTask `
    -TaskName "Larry Darry" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest `
    -Force
```

Replace `D:\path\to\vault` with your actual vault path.

---

## Adaptive Scheduling

Darry's core advantage over a flat batch runner is adaptive scheduling. The timeline for a typical night:

```
22:00 --- LIGHT SLEEP START ---------------------
          | Vault hygiene
          | Inbox triage
          | Heartbeat check
          | Queue cleanup
          | Tmp cleanup
          | Git status
          v
00:00 --- DEEP SLEEP START (if conditions met) --
          | Memory indexing (GPU)
          | KG hygiene
          | Knowledge distillation
          | Diary compression
          | Archive sweep
          v
04:00 --- REM SLEEP START (if triggered) --------
          | Cross-domain analysis (Opus)
          | Creative suggestions
          | Pattern recognition
          v
05:30 --- MORNING BRIEF -------------------------
          | Summarize night's work
          | Actionable items first
          | REM insights last (if REM ran)
          | Hand to delivery agent
          v
06:00 --- DARRY SLEEPS ---------------------------
```

**Adaptation rules:**

- If Light Sleep finds critical problems, escalate immediately (Telegram notification via delivery agent). Do not wait for morning.
- If Deep Sleep conditions are not met, skip directly to REM (if triggered) or morning brief.
- If REM is not triggered, morning brief is based on Light + Deep only.
- If everything is clean and no phases beyond Light are needed, the brief is short: "Quiet night. Nothing to report."
- If Light Sleep finishes early, Deep Sleep can start early. Phases are sequential but not time-locked.

---

## Model Selection

Each phase uses a different model, matched to the cognitive load:

| Phase | Model | Rationale |
|-------|-------|-----------|
| Light Sleep | Haiku | Fast, cheap. Maintenance tasks do not need deep reasoning |
| Deep Sleep | Sonnet | Stronger reasoning for knowledge distillation and KG hygiene |
| REM Sleep | Opus | Creative, associative. Pattern recognition across domains |

This is configurable in `darry-config.json`. The key insight: you do not need your most expensive model for cleanup tasks, and you do not want your cheapest model doing creative synthesis.

---

## Bus Integration

Darry communicates via the brains-bus (brain name: `darry`).

```bash
# Check Darry status
python 03-projects/ml-brainclone/bus/brains-bus.py read --brain darry

# Request a dream on a specific topic
python 03-projects/ml-brainclone/bus/brains-bus.py post \
    --from larry \
    --to darry \
    --kind dream-request \
    --payload '{"topic":"project overlap","context":"Are projects A and B converging?"}'
```

### Event types

| Direction | Kind | Payload |
|-----------|------|---------|
| Darry -> * | `darry-phase-start` | `{phase, model, jobs[]}` |
| Darry -> * | `darry-phase-done` | `{phase, duration_min, findings[]}` |
| Darry -> carry | `carry-batch` | `{pipeline: "morgonbrief", items[]}` |
| Darry -> larry | `darry-critical` | `{finding, severity}` — mid-night escalation |
| Larry -> darry | `dream-request` | `{topic, context}` — "dream about X" |

Parry sees all bus events, including Darry's. Nightly work is not exempt from oversight.

---

## Status Check

Darry writes a heartbeat file while running:

```
03-projects/ml-brainclone/notifications/darry.heartbeat
```

The heartbeat is updated every 15 seconds. If it goes stale (>2 min), the Task Scheduler restarts the process.

```powershell
# Check Darry heartbeat
powershell -File 03-projects/darry/startup/darry-status.ps1
```

---

## Upgrade Path from Flat Batch Runner

If you are currently using a sequential nightly batch runner (batch 1 through N, running unconditionally every night), Darry replaces it in phases:

| Migration Phase | What Happens | Status |
|-----------------|-------------|--------|
| **Phase 1 — Parallel** | **Darry runs alongside the existing batch runner. Compare outputs** | **Active** |
| Phase 2 — Light takeover | Darry takes over cleanup/triage batches. Disable corresponding batch jobs | Pending |
| Phase 3 — Deep takeover | Darry takes over indexing, KG, distillation batches. Disable those batch jobs | Pending |
| Phase 4 — Full takeover | Darry owns all nightly work. Remove the old batch runner cron/scheduler entry | Pending |
| Phase 5 — REM activation | Enable REM Sleep. This is net-new functionality with no batch equivalent | Pending |

### Current State: Migration Mode

Darry v1 is deployed and running in `migration_mode: true`. In this mode:

- Darry runs as a daemon alongside the legacy nightly batch runner
- Both systems produce output independently
- Darry evaluates conditions and logs what it *would* do
- The legacy runner still handles actual nightly work
- This allows comparing Darry's decisions against legacy output before handover

Key implementation details from the running system:

```python
# darry-config.json -- migration_mode flag
{
  "migration_mode": true,
  "poll_seconds": 60,
  "heartbeat_every": 30
}
```

The daemon polls every 60 seconds, checking if the current time falls within the night window (22:00-06:00). When the window opens and tonight's phases have not yet run, it executes them sequentially with interruptible waits between phases.

### Mapping old batches to Darry phases

| Old Batch | Darry Phase | Change |
|-----------|-------------|--------|
| Cleanup/hygiene | Light Sleep | Same scope, better structured output |
| Inbox sort | Light Sleep | Same scope |
| Memory indexing | Deep Sleep | Now conditional — skips if few changes |
| External feed ingest | Light Sleep | Move to inbound pipeline agent if available |
| Knowledge distillation | Deep Sleep | Now conditional |
| KG hygiene | Deep Sleep | Now conditional |
| Morning brief | Darry compile | Summarizes ALL phases, not just one batch |
| (none) | REM Sleep | Entirely new — creative/pattern phase |

The key upgrade: conditional execution. The old batch runner does everything every night regardless of need. Darry evaluates conditions and skips phases that have nothing to do. This saves model cost and produces cleaner reports (no "nothing found" noise).

### Lessons from Parallel Running

Running both systems simultaneously revealed several patterns:

1. **Singleton shutdown before indexing.** The nightly batch runner must shut down the MCP singleton before running `mempalace mine`, because the singleton holds ChromaDB's HNSW index open. Without this, the indexer deadlocks and the batch runner's timeout kills everything silently. Use the singleton's control channel and fall back to a kill only if it does not answer -- a hard kill skips the HNSW flush and can diverge the index. Set a maintenance flag first so the watchdog does not restart the primary mid-run. Darry handles this internally. See [daemon-stability.md](daemon-stability.md) pattern #9.

2. **PATH hardening on Windows.** When Task Scheduler runs bash scripts, the WSL shim in `WindowsApps` can intercept `bash` calls. The batch runner's PATH must explicitly prepend Git Bash and exclude WindowsApps. See [daemon-stability.md](daemon-stability.md) pattern #10.

3. **Condition evaluation is cheap.** Darry checks vault changes, inbox age, and days since last run in <1 second. The decision "should Deep Sleep run?" costs nothing compared to running it unconditionally.

4. **"Already ran tonight" guard.** A state file tracks which phases completed tonight. If the daemon restarts mid-night (crash, update), it resumes from the next uncompleted phase instead of re-running everything.

---

## Integration with Other Agents

| Agent | Relationship |
|-------|-------------|
| **Parry** | Monitors all Darry phases. Sees bus events. Can block if privacy violation detected in REM output |
| **Tarry** | Provides timing coordination. Can trigger Darry phases outside normal schedule if needed |
| **Carry** | Receives morning brief for delivery (email, vault storage) |
| **Milla** | Deep Sleep dispatches memory indexing work to Milla |
| **Scarry** | Hooked into Deep Sleep. Darry runs Scarry scanner, feeds results to REM if triggered |
| **Warry** | Deep Sleep runs daily mood snapshot (sentiment analysis) |
| **Larry** | Receives morning brief at session init. Can request dream topics via bus |

---

## See Also

- [daemon-stability.md](daemon-stability.md) -- Daemon stability patterns (start scripts, heartbeats, circuit breakers)
- [parry-setup.md](parry-setup.md) -- Parry daemon (same process model)
- [tarry-setup.md](tarry-setup.md) -- Tarry daemon (timing coordination)
- [brains-bus-setup.md](brains-bus-setup.md) -- Inter-agent event bus
- [task-dispatch.md](task-dispatch.md) -- Task queue system
- [architecture-overview.md](architecture-overview.md) -- Agent ecosystem overview
- [memory-system.md](memory-system.md) -- Milla / MemPalace setup
