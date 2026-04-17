# Brains-bus Setup — Inter-Agent Event Bus

SQLite-based event bus between Larry sessions, Barry, Harry — with Parry as the guardian middle-layer that verdicts every event before the recipient sees it.

- **Larry** — thinks, plans, orchestrates
- **Barry** — sees (images)
- **Harry** — hears and speaks (audio)
- **Parry** — guards, filters, judges (now also the bus gatekeeper)

---

## Why a bus?

Without it:
- Multiple Larry sessions don't know about each other.
- Barry and Harry are fire-and-forget scripts — no feedback loop.
- Parry has no runtime role; it's a content filter only.

With it:
- Sessions broadcast `status` and see who's alive.
- Larry posts `barry-request`, Barry picks up, posts `barry-result` with matching `correlation_id`.
- Parry sees every event before delivery — can block privacy violations, flag destructive ops.
- Diary + knowledge graph remain long-term memory. Bus is short-term + commands.

---

## Diagram

```
                           +----------------------+
                           |   Parry guardian     |
                           |  (parry_service.py)  |
                           |  poll 1.5s, N rules  |
                           +----------+-----------+
                                      |
                            set_verdict(pass/flag/block)
                                      |
                                      v
  +---------+   post    +------------------------------+    read    +---------+
  |  Larry  +---------->+                              +----------->+  Barry  |
  | session |           |      events (SQLite WAL)     |            | scripts |
  +---------+           |                              |            +---------+
                        |  id, from, to, kind, payload |
  +---------+   post    |  ts, verdict, note, read_by  |   read     +---------+
  |  Harry  +---------->+                              +----------->+  Larry  |
  | scripts |           +---------------+--------------+            |session2 |
  +---------+                           ^                           +---------+
                                        |
                                        | tail / stats / pending
                                        |
                                 +------+-------+
                                 | brains-bus   |
                                 |     CLI      |
                                 +--------------+
```

---

## Layout

```
03-projects/ml-brainclone/bus/
  brains_bus.py         # core lib
  bus_client.py         # high-level helpers (emit/inbox/request/reply/session)
  parry_guardian.py     # rule engine
  parry_service.py      # service wrapper with PID + heartbeat + log
  brains-bus.py         # CLI
  startup/
    parry-start.ps1
    parry-stop.ps1
    parry-status.ps1
  README.md
```

Database lives at a private path (example: `_private/brains-bus.db` — WAL mode) because payloads may contain sensitive content that Parry is responsible for keeping in its lane.

---

## Schema

```sql
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_brain      TEXT NOT NULL,              -- larry | barry | harry | parry | ...
    to_brain        TEXT NOT NULL,              -- same set + '*' for broadcast
    kind            TEXT NOT NULL,              -- see event conventions
    payload         TEXT NOT NULL,              -- JSON UTF-8
    ts              TEXT NOT NULL DEFAULT (datetime('now')),
    parry_verdict   TEXT,                       -- NULL | 'pass' | 'flag' | 'block'
    parry_note      TEXT,                       -- explanation on flag/block
    parry_ts        TEXT,                       -- when Parry set verdict
    read_by         TEXT NOT NULL DEFAULT '[]', -- JSON array of brain names
    correlation_id  TEXT                        -- optional 12-char hex for request/reply
);

CREATE INDEX idx_inbox   ON events(to_brain, parry_verdict);
CREATE INDEX idx_pending ON events(parry_verdict);
CREATE INDEX idx_ts      ON events(ts);
CREATE INDEX idx_corr    ON events(correlation_id);
```

Key properties:
- `read_by` is a JSON array → idempotent consumption per brain.
- `verdict = NULL` means "awaiting Parry". Recipients don't see it yet.
- `verdict = 'block'` means Parry rejected it. Stays in DB for audit, recipients never see it.
- Broadcast (`to='*'`) is read by anyone calling `read_inbox(brain)` — but only once per brain.

---

## Quick start

```bash
# 1. Initialize DB
python 03-projects/ml-brainclone/bus/brains-bus.py init

# 2. Start Parry service (once per boot)
powershell -File 03-projects/ml-brainclone/bus/startup/parry-start.ps1

# 3. Post manually
python brains-bus.py post --from larry --to barry --kind barry-request \
  --payload '{"task":"generate","prompt":"...","n":2}'

# 4. Read inbox
python brains-bus.py read --brain barry

# 5. Tail + stats
python brains-bus.py tail --limit 50
python brains-bus.py stats
```

---

## Python integration

```python
# Barry-style script
import sys
sys.path.insert(0, "03-projects/ml-brainclone/bus")
from bus_client import session, emit, inbox, reply

with session("barry", meta={"model": "chroma"}):
    emit("barry-status", {"state": "ready"})

    for ev in inbox("barry", timeout=300):  # listen 5 min
        if ev["kind"] == "barry-request":
            counter = generate(ev["payload"])
            reply(ev, "barry-result", {"counter": counter, "ok": True})
```

---

## Parry rules (starter set)

| Rule | Trigger | Verdict |
|---|---|---|
| `privacy_to_external` | private-path content heading to external/email/publish/linkedin/slack | **block** |
| `destructive_git` | git push --force, reset --hard, rm -rf, clean -f | **flag** |
| `anon_model_cost` | Barry request with a paid-credit model | **flag** |
| `email_external` | Email to a non-self recipient | **flag** |
| `forefront_leakage` | Cross-contamination between separated work contexts | **flag** |

Add rules by decorating a function with `@rule` in `parry_guardian.py`. First rule to return a tuple wins.

```python
@rule
def my_rule(ev: dict):
    if ev["kind"] == "email-send" and suspicious(ev["payload"]):
        return ("flag", "suspicious email")
    return None
```

---

## Event conventions

### `kind` — naming
- `session-start`, `session-end`, `session-error` — script lifecycle
- `status` — broadcast state (who's alive)
- `barry-request` / `barry-result` — image jobs
- `harry-request` / `harry-result` — audio jobs
- `email-send`, `email-draft`
- `git-op`, `shell` — destructive commands
- `linkedin-post`, `publish` — external publishing

### Payload format
- Always JSON UTF-8
- Common keys: `model`, `prompt`, `n`, `to`, `subject`, `body`
- Explicit `privacy: N` if content is level-classified

---

## Operations

### Starting at boot
Options:
1. **Manual** — run `parry-start.ps1` first time per session
2. **Task Scheduler** — "At startup" trigger → runs `parry-start.ps1` (recommended for persistent setup)
3. **Terminal startup** — put it in your WT/PS profile

### Monitoring
- PID file: `notifications/parry-guardian.pid`
- Heartbeat: `notifications/parry-guardian.heartbeat` (every 30 s)
- Log: `notifications/parry-guardian.log`
- Status script: `startup/parry-status.ps1`

If heartbeat > 2 min stale, Parry is hung. Restart with `parry-stop.ps1` + `parry-start.ps1`.

---

## Performance + limits (v1)

- **Latency:** Parry poll 1.5s + consumer poll 2s = 1–4s end-to-end. Fine for human-in-the-loop, not for real-time ML.
- **Throughput:** SQLite WAL handles 1000+ events/s locally. `read_by LIKE` queries slow at 10k+ events per inbox.
- **Cleanup:** none in v1. Plan: archive events older than 30 days.
- **Resilience:** if Parry is down, events pile up as pending. No auto-flush (deliberate: safety > availability).

If v1 becomes insufficient: swap backend to Redis pub/sub or ZeroMQ IPC. The API (`emit / inbox / request / reply`) is designed to survive the swap.

---

## Related
- [Parry Setup](parry-setup.md) — Parry as privacy filter (content gatekeeper)
- [Larry Setup](larry-setup.md)
- [Barry Setup](barry-setup.md)
- [Harry Setup](harry-setup.md)
