# Oversight: Human in the Loop by Action Type

One function answers a single question before anything leaves the system in your name: can this action happen without you?

## The problem it solves

A personal agent system grows dozens of small side effects over time: sending mail, posting to a public channel, restarting a daemon, deleting a file outside version control, spending money on a paid API call. Each one gets approved ad hoc, in whatever chat happened to be open, with no record of what was said yes to.

That falls apart in three specific ways, all observed in a running system before the fix. Questions asked in chat got buried in a notification queue with no answer field and nothing that noticed they went unanswered. An approval given in a Telegram message ("yes, send it") bound to nothing: if the draft changed between the question and the answer, the new version went out on the old yes. And there was no single place that could answer "is this action allowed to happen on its own", because the rule lived as prose scattered across a memory file, a project doc and a few code comments.

## The mechanism

Every action type gets classified into one of three modes:

- `in_loop`: the action does not happen until you say yes to the exact content in question.
- `on_loop`: the action happens after a hold window. You can undo it during the window, and it shows up in your next status digest either way.
- `autonomous`: the action happens and gets logged.

The table lives in one config file, read by one module. Nothing else in the codebase hardcodes a rule about what needs approval.

```python
# oversight.py
MODES = ("autonomous", "on_loop", "in_loop")
RANK = {m: i for i, m in enumerate(MODES)}  # higher = stricter

# Hard floors: can be raised by config, never lowered.
HARD_FLOORS = {
    "publish_post": "in_loop",
    "delete_external": "in_loop",
    "paid_call": "in_loop",
    "daemon_restart": "in_loop",
}

def oversight_for(action: str, payload: dict | None = None) -> dict:
    row = load_config()["actions"].get(action)
    mode = row["mode"] if row else "on_loop"  # unknown action defaults to caution
    floor = HARD_FLOORS.get(action)
    if floor and RANK[mode] < RANK[floor]:
        mode = floor
    return {"action": action, "mode": mode, "hold_minutes": row.get("hold_minutes", 0)}
```

Call sites never hardcode a rule. They ask `oversight_for("send_mail_external")` and act on the answer. A daemon and an interactive session ask the same function, so the two floors, the daemon guard and the session hook, cannot drift apart.

Two enforcement points, one source of truth:

- **Daemons.** A privacy and tone gate on the internal event bus checks every outbound event against `oversight_for()` before it leaves. In the reference system this gate is called Parry.
- **Interactive sessions.** A `PreToolUse` hook intercepts shell commands before they run, even in a fully autonomous session, and classifies each one (does this send mail to someone other than you, does this push to a shared repo, does this restart a daemon). Anything that isn't `autonomous` gets held or asked about instead of executed.

```python
# hook pseudocode
def decide(command: str) -> tuple[str, str]:
    action = classify(command)          # None if the command has no external effect
    if action is None:
        return "allow", ""
    result = oversight_for(action)
    if result["mode"] == "autonomous":
        log_action(action)
        return "allow", ""
    if result["mode"] == "in_loop":
        return "ask", f"{action} requires your yes for this exact command."
    # on_loop: queue it, don't run it directly
    hold_until = queue_with_hold(action, command, result["hold_minutes"])
    return "deny", f"Queued, delivers at {hold_until} unless you cancel."
```

## Questions with a paper trail

Anything the agent needs to ask you goes through one module, never free text pasted into a chat. A question carries a deadline, a default answer, and a fallback behavior (`wait`, `default`, or `drop`) for what happens if you never answer:

```json
{
  "id": "ask-7f3a",
  "kind": "memory_conflict",
  "question": "Two notes disagree about X. Which one is current?",
  "options": ["first", "second", "both, different contexts"],
  "default": null,
  "content_hash": "sha256:...",
  "expires_at": "2026-09-24T02:10:00+02:00",
  "fallback": "wait",
  "status": "open"
}
```

The `content_hash` matters more than it looks. If the underlying content changes between when the question was asked and when you answer it, the answer is thrown away and the question is asked again against the new content. A yes to an old draft should never apply to a new one. `in_loop` actions are never allowed to use `fallback: default`: code enforces that at creation time, because letting a high-stakes action fall back to a default answer defeats the point of gating it.

## How to adopt this in a fork

1. Write down every action type your system takes that has an external or irreversible effect: sending a message to someone other than you, posting publicly, deleting something outside version control, spending money, restarting a service. Assign each one a mode.
2. Build the single config file (JSON is fine) and the resolver function. Keep a small set of hard floors in code for the handful of actions that must never be downgraded, no matter what the config says.
3. Wire the resolver into your daemon-side gate (wherever outbound events already pass through one chokepoint) and into a `PreToolUse` hook for interactive sessions, if your harness supports one. Both call the same function.
4. Build the questions-with-a-hash module before you build anything that asks you things. Retrofitting content hashing onto an existing ad hoc approval flow is harder than starting with it.
5. Add a status line or digest section that lists what happened autonomously in your name over the last day. Zero actions should render as an empty section, not as "nothing to report", so you can tell the difference between "nothing happened" and "the report is broken".

## Pitfalls

**Unknown actions defaulting to "allow" instead of "ask".** The failure mode where a new action type gets added to the code before it gets added to the config is common. Default unknown actions to the more cautious mode, not the more permissive one.

**A hold window that only exists on paper.** If your `on_loop` handler just logs a warning and lets the command run anyway, the undo window is fiction. The action must actually be queued and actually wait, with a real delivery step at the end of the hold, or the whole tier collapses into `autonomous`.

**Coverage gaps in the interactive hook.** A hook that only matches shell commands will miss anything a browser-automation tool or an MCP server does directly. Document what the hook does not cover rather than pretending it covers everything; it's better to know a gap exists than to discover it after something ships that shouldn't have.

**Marker phrases for "I'm standing right here".** It helps to have an explicit override phrase (something like `# approved-by-human: <reason>`) for the case where you are physically present and typing the command yourself. Log the override with its reason rather than silently trusting it; you want the record even when you are the one who said yes.

## See also

- [decision-gate.md](decision-gate.md) for the typed decision model that classifies whether something needs a human decision at all before it reaches this layer
- [status-file.md](status-file.md) for where `on_loop` actions and open questions surface to you
