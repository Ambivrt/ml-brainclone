"""claude_headless.py -- shared environment for unattended `claude -p` calls.

What every headless call has in common:

1. MCP wait. With enableAllProjectMcpServers in the vault, every `claude -p`
   with its cwd in the vault connects every MCP server before the first turn.
   CLAUDE_CODE_MCP_STARTUP_WAIT_MS caps that. Pure text jobs do not wait at
   all; jobs that need the memory server wait at most ten seconds instead of
   the full MCP timeout when it is down.

2. Cache boundary in --system-prompt. Text above
   __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ is cached globally, what is below may
   vary per session.

3. WebFetch off. Text jobs that read the owner's material (graph extraction,
   mail, graders) never need the web. web_fetch=False sets
   CLAUDE_CODE_DISABLE_WEB_FETCH and closes that way out.

4. Patient backoff on 529. Unattended jobs (night shift, brief, task watcher)
   have nobody waiting for the answer. patient=True sets
   CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS so retries spread out while the
   API is overloaded instead of giving up. Chat replies keep the default,
   where response time weighs more. The ceiling per wait is raised with
   CLAUDE_CODE_OVERLOADED_RETRY_MAX_DELAY_MS to 64 s, the highest the CLI
   accepts.

5. Wait out limits, with a ceiling. limit_wait_s sets CLAUDE_CODE_RETRY_WATCHDOG
   with two ceilings: _MAX_WAIT_MS for 429/529 and _MAX_USAGE_LIMIT_WAIT_MS for
   the usage limit. If the limit resets further away than the ceiling, the call
   ends as before. _USAGE_LIMIT_RECHECK_MS notices a limit that lifts before
   the announced time. Only jobs without their own quota handling and with a
   timeout above the ceiling (task watcher, 30 min) use it. Short jobs would
   just hang until the subprocess timeout.

6. Honest outcome. parse_print_output() reads the JSON reply from
   `claude --print --output-format json`. A reply with is_error or a subtype
   other than "success" is a failure even when stdout is valid JSON, and a
   `TASK-FAILED: <reason>` line at the end of the reply lets the job reject
   itself. The number of calls the loop guard denied comes along
   (loop_guard.py).

7. Measuring. parse_print_output(..., job="name") writes the run's turns and
   cost to the daily ledger in job_budget.py. Measurement only, no ceilings.

HEADLESS=1 lets hooks tell a daemon session from one the owner sits in, so a
privacy hook can block the former and only warn the latter.
"""
from __future__ import annotations

import json
import os

MCP_WAIT_ENV = "CLAUDE_CODE_MCP_STARTUP_WAIT_MS"
MCP_WAIT_NONE = 0          # text only: nudges, graders, extraction
MCP_WAIT_TOOLS = 10_000    # jobs that use memory or other MCP tools

SYSTEM_PROMPT_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
WEB_FETCH_OFF_ENV = "CLAUDE_CODE_DISABLE_WEB_FETCH"
OVERLOADED_DELAY_ENV = "CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS"
OVERLOADED_DELAY_PATIENT_MS = 5_000

OVERLOADED_MAX_DELAY_ENV = "CLAUDE_CODE_OVERLOADED_RETRY_MAX_DELAY_MS"
# Ceiling of the same backoff. The CLI accepts 32000 to 64000, anything else counts as unset
OVERLOADED_MAX_DELAY_PATIENT_MS = 64_000

RETRY_WATCHDOG_ENV = "CLAUDE_CODE_RETRY_WATCHDOG"
WATCHDOG_MAX_WAIT_ENV = "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS"
WATCHDOG_USAGE_WAIT_ENV = "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS"
WATCHDOG_RECHECK_ENV = "CLAUDE_CODE_RETRY_WATCHDOG_USAGE_LIMIT_RECHECK_MS"
WATCHDOG_RECHECK_MS = 300_000
# 30-minute jobs: at most 20 min of waiting, at least 10 min left for the job itself
LIMIT_WAIT_30MIN_JOB_S = 20 * 60


def headless_env(mcp_wait_ms: int, extra: dict[str, str] | None = None, *,
                 web_fetch: bool = True, patient: bool = False,
                 limit_wait_s: int = 0) -> dict[str, str]:
    """Environment for subprocess.run(["claude", "--print", ...], env=...).

    limit_wait_s > 0 waits out 429/529 and the usage limit for that long."""
    env = {**os.environ, MCP_WAIT_ENV: str(int(mcp_wait_ms)), "HEADLESS": "1"}
    if not web_fetch:
        env[WEB_FETCH_OFF_ENV] = "1"
    if patient:
        env[OVERLOADED_DELAY_ENV] = str(OVERLOADED_DELAY_PATIENT_MS)
        env[OVERLOADED_MAX_DELAY_ENV] = str(OVERLOADED_MAX_DELAY_PATIENT_MS)
    if limit_wait_s > 0:
        wait_ms = str(int(limit_wait_s) * 1000)
        env[RETRY_WATCHDOG_ENV] = "1"
        env[WATCHDOG_MAX_WAIT_ENV] = wait_ms
        env[WATCHDOG_USAGE_WAIT_ENV] = wait_ms
        env[WATCHDOG_RECHECK_ENV] = str(WATCHDOG_RECHECK_MS)
    if extra:
        env.update(extra)
    return env


def split_system_prompt(static: str, dynamic: str) -> str:
    """The system prompt with the cache boundary between the fixed and the varying part.
    An empty varying part is dropped: an empty tail gives an empty text block."""
    dynamic = dynamic.strip()
    if not dynamic:
        return static
    return f"{static.rstrip()}\n{SYSTEM_PROMPT_BOUNDARY}\n{dynamic}"


FAILURE_MARKER = "TASK-FAILED:"
FAILURE_CONVENTION = (
    "\n\nIf you could not complete the task: end the reply with ONE line\n"
    "TASK-FAILED: <what was not done and why>\n"
    "An honest TASK-FAILED is better than half a job reported as done."
)
# The marker only counts among the last lines, so a quote of the convention
# in the middle of a reply does not fail the job.
_FAILURE_TAIL_LINES = 5


def failure_marker(reply: str) -> str | None:
    """The reason from a TASK-FAILED line among the reply's last lines, else None."""
    lines = [ln.strip().strip("*_`> ").strip() for ln in (reply or "").splitlines() if ln.strip()]
    for line in reversed(lines[-_FAILURE_TAIL_LINES:]):
        if line.upper().startswith(FAILURE_MARKER):
            return line[len(FAILURE_MARKER):].strip() or "the job rejected itself without a reason"
    return None


def parse_print_output(stdout: str, returncode: int, job: str | None = None) -> dict:
    """Interpret stdout from `claude --print --output-format json`.

    -> {"ok", "reply", "session_id", "failure", "loop_denials"}
    ok is False when the process failed, when the CLI itself reports an error
    (is_error, subtype other than "success") or when the reply ends with
    TASK-FAILED. failure carries the reason in plain text, never the whole reply.
    Text that is not JSON is taken as the reply itself.
    """
    out = (stdout or "").strip()
    reply, session_id, failure = out, "", None
    try:
        data = json.loads(out) if out else None
    except ValueError:
        data = None
    if job:
        import job_budget
        job_budget.record(job, data if isinstance(data, dict) else {})
    if isinstance(data, dict):
        reply = str(data.get("result") or "")
        session_id = str(data.get("session_id") or "")
        subtype = str(data.get("subtype") or "")
        if data.get("is_error") or (subtype and subtype != "success"):
            first = reply.strip().splitlines()[0][:200] if reply.strip() else ""
            failure = f"CLI ended with {subtype or 'is_error'}" + (f": {first}" if first else "")
    if failure is None:
        marker = failure_marker(reply)
        if marker:
            failure = marker
    if failure is None and returncode != 0:
        failure = f"exit {returncode}"
    loop_denials = 0
    if session_id:
        try:
            import loop_guard
            loop_denials = loop_guard.denials(session_id)
        except Exception:
            pass
    return {"ok": failure is None, "reply": reply, "session_id": session_id,
            "failure": failure, "loop_denials": loop_denials}
