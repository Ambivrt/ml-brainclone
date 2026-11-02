"""protected_files.py -- files an unattended headless job never writes.

Borrowed from GitHub Agentic Workflows (gh-aw, GA 2026-10-28),
`protected-files`: the agent's own instructions and security code must not be
changed by the agent itself. A prompt injection that reaches a headless job
should not be able to write itself into CLAUDE.md, a hook or the oversight
rules and survive into the next session.

  protected  CLAUDE.md (any), .claude/settings*.json, .claude/hooks|agents|
             skills|commands, session-init.md, .mcp*.json, .git/hooks,
             the deploy script, the secrets directory under the config dir,
             and the security modules (oversight, extern_taint, privacy_taint,
             privacy_gate, credential_scan, loop_guard, protected_files) in
             scripts/ or lib/. Add your own patterns with
             LARRY_PROTECTED_EXTRA (regexes separated by ";", matched against
             the lowercased, forward-slash path)
  enforced   the privacy guard hook calls tool_hit() and denies
             Edit/Write/NotebookEdit/MultiEdit on a protected file while
             LARRY_HEADLESS=1. Relative paths are resolved against the
             session cwd
  exempt     orders from the owner. Chat sessions and tasks whose sender is
             the owner (see envelope.task_origin) are started with
             LARRY_OWNER_ORDER=1. The environment is set by whoever starts
             the process, the agent cannot change its own. Interactive
             sessions are never affected
  way out    the job writes the change as a proposal in its report

Shell commands are not inspected. A word-pattern rule could not tell source
from target (`cat CLAUDE.md > report.txt` was denied) and was backed out
after an adversarial review. Known holes: shells and scripts that write the
file, and batch runs that do not set LARRY_HEADLESS.
"""
from __future__ import annotations

import os
import re

HEADLESS_ENV = "LARRY_HEADLESS"
# Set by the chat listener and the task watcher when the owner ordered the job.
OWNER_ENV = "LARRY_OWNER_ORDER"
EXTRA_ENV = "LARRY_PROTECTED_EXTRA"

# The path is lowercased and normalised to "/" before matching.
_PATTERNS = [
    r"(?:^|/)claude\.md$",
    r"/\.claude/settings(?:\.local)?\.json$",
    r"/\.claude/(?:hooks|agents|skills|commands)/",
    r"/\.claude/skills-[a-z]+\.json$",
    r"/\.claude/session-init\.md$",
    r"(?:^|/)\.mcp(?:-[a-z]+)?\.json$",
    r"/\.git/hooks/",
    r"(?:^|/)(?:larry-)?deploy\.(?:ps1|sh)$",
    r"/config/secrets(?:/|$)",
    r"(?:^|/)(?:scripts|lib)/"
    r"(?:oversight\.(?:py|json)|extern_taint\.py|privacy_taint\.py|privacy_gate\.py"
    r"|credential_scan\.py|loop_guard\.py|protected_files\.py)$",
]

WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")


def _compiled(env: dict | None = None) -> re.Pattern:
    env = os.environ if env is None else env
    patterns = list(_PATTERNS)
    for extra in (env.get(EXTRA_ENV) or "").split(";"):
        extra = extra.strip()
        if not extra:
            continue
        try:
            re.compile(extra)
        except re.error:
            continue
        patterns.append(extra)
    return re.compile("|".join(f"(?:{p})" for p in patterns))


def _norm(path: str, cwd: str = "") -> str:
    p = str(path or "")
    if p and cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    if p:
        p = os.path.normpath(p)
    return p.replace("\\", "/").lower()


def is_protected(path: str, cwd: str = "") -> bool:
    return bool(path) and bool(_compiled().search(_norm(path, cwd)))


def applies(env: dict | None = None) -> bool:
    """The protection applies to unattended headless jobs, not to the owner's orders."""
    env = os.environ if env is None else env
    return env.get(HEADLESS_ENV) == "1" and env.get(OWNER_ENV) != "1"


def tool_hit(tool: str, tool_input: dict, cwd: str = "") -> str | None:
    """What the tool call writes of the protected set, or None."""
    if tool not in WRITE_TOOLS:
        return None
    data = tool_input if isinstance(tool_input, dict) else {}
    path = str(data.get("file_path") or data.get("notebook_path") or "")
    return f"{tool} on {path[:120]}" if is_protected(path, cwd) else None


DENY_REASON = (
    "PROTECTED: unattended headless jobs do not change agent instructions, hooks, settings "
    "or security code ({hit}). If the file needs to change: write the change as a proposal "
    "(file, what, why, diff) in the report and move on.")
