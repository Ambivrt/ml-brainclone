# Headless Guards

Small guards around unattended (headless) agent sessions: loop stop, protected
files, per-job measurement, outside-text taint, credential scan, sender
envelope and skill hygiene. Each is a standalone Python module in `scripts/`
with no dependency on the rest of the stack. Tests: `tests/test_headless_guards.py`.

## Why they exist

An unattended session has no one next to it. It reads text other people
wrote (web pages, mail, issue threads, scraped feeds) and it holds tools that
can act. Nobody is there to notice that it is stuck in a loop, that a
fetched page is steering it, or that it is rewriting its own instructions.
These guards are the floor under such sessions. The rule they extend is in
`docs/security-untrusted-input.md`: text from outside is data, not orders.

Interactive sessions are mostly left alone. The owner sits there, sees the
prompt and decides. Every guard that blocks keys on `LARRY_HEADLESS=1`, set by
whoever starts the process (task watcher, nightly runner), never by the agent.

## The guards

| Module | What it does |
|--------|--------------|
| `loop_guard.py` | Counts identical tool calls per session. The same call with the same response 4 times in a row, or the same call 10 times in total, is blocked. A new Edit/Write resets the counters. Waiting tools (Monitor, event waits) are exempt |
| `protected_files.py` | Path list of files a headless job never writes: `CLAUDE.md`, `.claude/settings*`, hooks, agents, skills, commands, `.mcp*.json`, `.git/hooks`, the deploy script, the secrets directory, and the security modules themselves. Extra regexes via `LARRY_PROTECTED_EXTRA` |
| `job_budget.py` | Measures, does not limit. One ledger per day: runs, turns, cost and longest run per job. `python scripts/job_budget.py report --days 7` |
| `extern_taint.py` | Marks a session as tainted once it has fetched text from outside (WebFetch, browser reads, `curl`, `gh issue`, mail reads). Taint is sticky per session. Modes: `enforce` (default) and `shadow` (log only) |
| `credential_scan.py` | One list of generic secret formats (cloud keys, GitHub tokens, private key headers, bearer tokens, `*_TOKEN=` assignments). `scan()` returns rule ids, `redact()` washes the text. A placeholder filter skips `$env:KEY` and `<your key>` |
| `envelope.py` | Decides who stands behind a task or bus row. The owner only counts when the source is a channel where the owner types and no agent is named as generator. Anything else is labelled "not from the owner" |
| `skill_usage.py`, `skill_lint.py` | Log which skills get used. The linter flags skills with no description, missing scripts, broken index links, files the index never links to, and skills unused for 30 days (a candidate list, nothing is archived) |

## How they wire together

```
Claude Code hooks            modules                       ledgers (LARRY_STATE_DIR)
-----------------            -------                       -------------------------
hooks/loop-guard.py     ->   loop_guard.py            ->   loop-guard/<session>.json, events.jsonl
hooks/extern-taint-read ->   extern_taint.py          ->   extern-taint/<session>.json, shadow.jsonl
hooks/skill-usage.py    ->   skill_usage.py           ->   skill-usage/usage.jsonl
privacy guard hook      ->   protected_files.py, credential_scan.py
oversight gate          ->   extern_taint.verdict()
task watcher            ->   envelope.py, session_pool (tainted sessions are not reused)
headless runner         ->   job_budget.record(), loop_guard.denials()  ->  job-budget/*.json
nightly run             ->   skill_lint.py
```

- **Hooks** read the event JSON on stdin and always exit 0. A failure in a
  guard never stops a tool. Only the explicit deny is returned.
- **Modules** hold the logic and are importable without side effects. The
  hooks find them next to themselves, in `LARRY_SCRIPTS_DIR`, or in
  `$VAULT_PATH/scripts`.
- **Ledgers** are small JSON or JSONL files. Directory per module:
  `LARRY_LOOP_GUARD_DIR`, `LARRY_EXTERN_TAINT_DIR`, `LARRY_JOB_BUDGET_DIR`,
  `LARRY_SKILL_USAGE_LOG`, else `$LARRY_STATE_DIR/<name>`, else
  `$VAULT_PATH/data/<name>`. State files are written atomically and swept
  after a week; the budget ledger keeps 30 days and takes a file lock.

The oversight gate asks `extern_taint.verdict()` before an outward action
(send mail, push, post). In a tainted headless session in enforce mode, an
action that would run on its own is raised to "needs the owner's yes", and a
`# owner-ok:` marker in the command is ignored, because the marker may have
been dictated by the text that was read. The task watcher sets
`LARRY_OWNER_ORDER=1` only for tasks whose envelope says the owner sent them,
which exempts those from the protected-file rule.

## Known limits

- Taint only sees the fetchers it has patterns for. Home-made scrapers, other
  MCP servers, and text another session wrote into the vault are holes.
- `protected_files` checks Edit/Write-type tools. It does not parse shell
  commands: a pattern rule could not tell source from target and was backed out.
- `loop_guard` thresholds and `job_budget` are measurements first. A turn cap
  and a daily cost cap were tried and removed again because the thresholds had
  no data behind them.

## Where they come from

Most were borrowed from other open harnesses and then tightened: loop stop and
skill archiving candidates from Hermes Agent 0.22, protected files and the per-run
log from GitHub Agentic Workflows, extern taint and the sender envelope from
OpenClaw, the skill lint rules from Harness^2. Each one was reviewed
adversarially by a second model before it went live, and several were narrowed
or backed out in that review. Treat the thresholds as starting points and
check the shadow logs on your own install before relying on enforce mode.
