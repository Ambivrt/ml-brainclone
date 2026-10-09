"""claude_headless.py -- shared environment for unattended `claude -p` calls.

Four things every headless call has in common:

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
   where response time weighs more.

HEADLESS=1 lets hooks tell a daemon session from one the owner sits in, so a
privacy hook can block the former and only warn the latter.
"""
from __future__ import annotations

import os

MCP_WAIT_ENV = "CLAUDE_CODE_MCP_STARTUP_WAIT_MS"
MCP_WAIT_NONE = 0          # text only: nudges, graders, extraction
MCP_WAIT_TOOLS = 10_000    # jobs that use memory or other MCP tools

SYSTEM_PROMPT_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
WEB_FETCH_OFF_ENV = "CLAUDE_CODE_DISABLE_WEB_FETCH"
OVERLOADED_DELAY_ENV = "CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS"
OVERLOADED_DELAY_PATIENT_MS = 5_000


def headless_env(mcp_wait_ms: int, extra: dict[str, str] | None = None, *,
                 web_fetch: bool = True, patient: bool = False) -> dict[str, str]:
    """Environment for subprocess.run(["claude", "--print", ...], env=...)."""
    env = {**os.environ, MCP_WAIT_ENV: str(int(mcp_wait_ms)), "HEADLESS": "1"}
    if not web_fetch:
        env[WEB_FETCH_OFF_ENV] = "1"
    if patient:
        env[OVERLOADED_DELAY_ENV] = str(OVERLOADED_DELAY_PATIENT_MS)
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
