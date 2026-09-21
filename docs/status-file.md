# The Status File: One Compiled View Instead of Seven Scattered Ones

A single deterministic file, rebuilt from existing queues on a schedule, answers four questions every time a session starts: what is waiting on you, what is broken, what is coming, and what happened since you last looked.

## The problem it solves

A system with several agents and several queues accumulates status surfaces faster than anyone reads them: a queue of open questions, a scanner that writes findings to a file nobody consumes, a daily note that only gets updated if a session remembers to update it, a notification queue with a `read` flag but no answer field. Each surface is individually reasonable. Together they mean that "what actually needs my attention right now" has no single answer, and the honest failure mode is silence: an automation stops running and nobody notices for days, because noticing was never anyone's job.

The reference system diagnosed this directly after a scheduled morning digest silently failed to arrive and was only caught by manual inspection. The fix was not another queue. It was one file that gets compiled from the existing queues, deterministically, with no model call involved, and a watchdog that alerts when a trusted automation misses its expected run.

## The mechanism

Two rules underpin the whole thing:

1. **Code compiles it, sessions only read it.** No status surface should depend on a session remembering to update a note by hand. The status file is built by a small, dependency-tolerant Python script that reads a fixed list of source files and never calls a model.
2. **Nothing dies silently.** Every queue either has a consumer, or it shows up in the status file as a count and an age. Every scheduled automation has an expectation registered somewhere, and if it misses that expectation, a separate watchdog process raises it to you once, rather than the failure just sitting in a log nobody tails.

The compiled file (the reference system calls it "läget", Swedish for "the situation") has a fixed set of sections, always in the same order, capped at a small number of lines total so it stays skimmable:

```
WAITING ON YOU     - open questions, pending approvals, oldest first
BROKEN             - failing automations, deploy drift, silent agents
COMING UP          - reminders and calendar items in the next 7 days
SINCE LAST TIME    - actions taken in your name, session handoff notes, commits
OPEN THREADS       - unresolved topics surfaced by a background scanner, top 5
QUEUES             - one line per queue: count and age of the oldest item
```

Every reader function is written to fail soft: a missing or corrupt source file produces an empty section and a note in a `sources_missing` list, not a crash that takes down the rest of the file.

```python
# status_file.py sketch
SECTIONS = ("waiting_on_you", "broken", "coming_up",
            "since_last_time", "open_threads", "queues")

def read_json_tolerant(path):
    try:
        return json.loads(path.read_text()), True
    except (OSError, json.JSONDecodeError):
        return None, False

def build(vault_path):
    sources_missing = []
    sections = {}
    for name, reader in READERS.items():
        data, ok = reader(vault_path)
        if not ok:
            sources_missing.append(name)
        sections[name] = data
    return render_markdown(sections), {"sections": sections, "sources_missing": sources_missing}
```

The file is written in two forms: a short markdown version meant for a human to read at the top of a session, and a JSON version with the same sections as lists of typed records (`id`, `text`, `age_hours`, `deadline`, `source`) for anything that wants to consume it programmatically, like a digest or a dashboard.

## The watchdog half

Compiling a status file solves "what's waiting", not "what silently stopped happening". A separate watchdog process holds a small table of expectations: name, earliest check time, and one or more checks (a scheduled task returned success today, a file with today's date exists, a log line matches a pattern). It runs on its own schedule, writes its own state file, and sends exactly one notification per broken expectation per calendar day, deduplicated by name and date, respecting quiet hours.

```json
{
  "name": "daily-digest",
  "earliest_check": "06:30",
  "checks": [
    {"type": "file_exists_today", "path": "VAULT_PATH/_private/digest-{today}.md"},
    {"type": "scheduled_task_ok", "task_name": "daily-digest-task"}
  ]
}
```

```python
def run_watchdog(expectations_path, state_path, now):
    for expectation in load_expectations(expectations_path):
        if now.time() < expectation.earliest_check:
            continue
        ok = all(check(e) for e in expectation.checks)
        state = load_state(state_path)
        was_ok = state.get(expectation.name, {}).get("ok", True)
        if not ok and was_ok:
            notify_once(expectation.name, now.date())
        state[expectation.name] = {"ok": ok, "checked_at": now.isoformat()}
        save_state(state_path, state)
```

An evening shutdown routine runs on the other end of the day: it summarizes what happened (sessions run, actions taken in your name, questions asked and answered, commits made) into a small daily record. That record feeds the "since last time" section the next morning, so the status file's history doesn't depend on any single day's session remembering to write it down.

## How to adopt this in a fork

1. List every queue and every scanner output your system currently produces that a human is supposed to look at eventually. Most systems have more of these than expected once you list them.
2. Write one reader function per source, each one tolerant of a missing or malformed file, each one returning a typed list of records rather than raw text.
3. Write the compiler that calls all the readers and renders both a markdown and a JSON form. Keep the total line count capped; an unbounded status file becomes exactly the kind of thing nobody reads.
4. Hook the compiler into whatever runs at the start of a session (a shell profile, an init script, a hook), and also run it on a short schedule (every 10 to 15 minutes) so the session-start read is usually a cache hit rather than a full rebuild.
5. Build the watchdog second. Start with two or three expectations that matter most (the automations you'd actually be upset to find had failed silently) and expand from there.
6. Decide where the file lives from a privacy standpoint. If it blends personal and work content, keep it out of anything that syncs to a shared or public location.

## Pitfalls

**Confusing "the system's own errors" with "things you need to act on".** A status file that reports every internal hiccup turns into noise you learn to ignore, which defeats the purpose. Route the system's own recoverable failures to a "broken" section that gets fixed quietly; only escalate to you when a function you rely on has actually failed to deliver (a digest didn't arrive, a daemon is down, a queue is growing).

**Rebuilding on every read.** If the compiler does file I/O and subprocess calls (checking git status, querying a task scheduler) on every single invocation, and it's invoked at the start of every session, it becomes a tax on session startup. Cache it and rebuild on a timer instead of on every read.

**A queue with no consumer disguised as "handled".** It is easy to write a scanner that dumps findings to a file and call the feature done. If nothing reads that file, it isn't a status surface, it's a write-only log. Every queue in the status file needs either an active consumer or a count-and-age line; there is no third option where it's fine to just exist.

**Watchdog alert fatigue.** A watchdog that lacks deduplication (by name and by day) will fire on every check cycle while something stays broken. Alert once when a problem starts, log recovery silently, and only re-alert on a new failure.

## See also

- [oversight.md](oversight.md) for the approval and hold-window mechanism that fills the "waiting on you" section
- [daemon-stability.md](daemon-stability.md) for the heartbeat and circuit-breaker patterns the watchdog builds on
