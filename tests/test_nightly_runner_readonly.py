"""Structural tests for scripts/nightly-runner.sh -- the untrusted-input
hardening of the morning brief path (see docs/security-untrusted-input.md).

nightly-runner.sh is bash and doesn't run inside pytest (Task Scheduler,
Claude CLI, gws, etc.). Instead of executing it, this reads the source and
checks it with regexes. The goal is to catch a regression where the morning
brief path loses restrict_readonly/capture_file, or where some other batch
(which should NOT be hardened) accidentally gets the same flags and loses a
tool it actually needs (Bash, MCP, etc.)."""
from __future__ import annotations

import re
from pathlib import Path

RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "nightly-runner.sh"
SOURCE = RUNNER_PATH.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """Extract a bash function's body (rough but sufficient: matching brace
    count from 'name() {' to its closing '}')."""
    marker = f"{name}() {{"
    start = SOURCE.index(marker)
    depth = 0
    i = start
    while i < len(SOURCE):
        if SOURCE[i] == "{":
            depth += 1
        elif SOURCE[i] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start:i + 1]
        i += 1
    raise AssertionError(f"Could not find the end of function {name}()")


RUN_BATCH_BODY = _function_body("run_batch")
RUN_MORNING_BRIEF_BODY = _function_body("run_morning_brief")


# --- run_batch: the restrict_readonly branch exists and is correct ----------

def test_run_batch_has_restrict_readonly_parameter():
    assert 'local restrict_readonly="${5:-false}"' in RUN_BATCH_BODY


def test_run_batch_has_capture_file_parameter():
    assert 'local capture_file="${6:-}"' in RUN_BATCH_BODY


def test_run_batch_restrict_readonly_branch_drops_dangerous_flag():
    assert 'perm_flags="--dangerously-skip-permissions"' in RUN_BATCH_BODY
    assert re.search(r'restrict_readonly.*=.*"true".*\n\s*perm_flags=""', RUN_BATCH_BODY)


def test_run_batch_restrict_readonly_branch_sets_readonly_tools():
    assert "--tools Read,Glob,Grep --strict-mcp-config" in RUN_BATCH_BODY


def test_run_batch_restrict_readonly_branch_never_sets_dangerous_tools():
    m = re.search(r'tool_flags="--tools ([^"]+)"', RUN_BATCH_BODY)
    assert m, "Could not find the tool_flags assignment"
    tools = m.group(1).split()[0]  # "Read,Glob,Grep"
    tool_names = tools.split(",")
    for dangerous in ("Bash", "Write", "Edit", "WebFetch", "NotebookEdit"):
        assert dangerous not in tool_names


def test_run_batch_never_wires_up_an_mcp_config_flag():
    """The scaffold's run_batch never had a live --mcp-config flag to begin
    with -- the hardening must not accidentally introduce one that a future
    edit could enable for the readonly path. (Mentions in comments are
    fine; only a real flag assignment would defeat --strict-mcp-config.)"""
    code_lines = [ln for ln in RUN_BATCH_BODY.splitlines() if not ln.strip().startswith("#")]
    assert not any("--mcp-config" in ln for ln in code_lines)


def test_run_batch_default_call_sites_do_not_pass_restrict_readonly():
    """Every OTHER batch (1, 2, 4, 5, 6, 7, 8) must still call run_batch
    without the hardening arguments -- none of them should accidentally
    inherit restrict_readonly/capture_file and lose Bash/MCP they need."""
    other_calls = re.findall(
        r'^\s*run_batch \d[a-z]?\s+"[^\n]*$', SOURCE, re.MULTILINE
    )
    assert other_calls, "Found no run_batch calls for other batches to check"
    for line in other_calls:
        if '"batch3-morning-brief.md"' in line or '"batch3b-daily-note.md"' in line:
            # These are called from inside run_morning_brief, checked separately.
            continue
        assert "true" not in line.split('"')[1:], line
        assert "Read,Glob,Grep" not in line


# --- run_morning_brief: calendar collection + hardened call + write helper --

def test_run_morning_brief_calls_collect_calendar_before_compilation():
    assert "collect-calendar.py" in RUN_MORNING_BRIEF_BODY
    calendar_pos = RUN_MORNING_BRIEF_BODY.index("collect-calendar.py")
    compile_pos = RUN_MORNING_BRIEF_BODY.index('run_batch 3 "Morning brief"')
    assert calendar_pos < compile_pos


def test_run_morning_brief_invokes_run_batch_with_hardening_flags():
    m = re.search(r'run_batch 3 "Morning brief"[^\n]*', RUN_MORNING_BRIEF_BODY)
    assert m, "Could not find the morning brief's run_batch call"
    line = m.group(0)
    assert '"true" "$brief_capture"' in line, line


def test_run_morning_brief_writes_via_brief_output_helper():
    assert "brief_output.py" in RUN_MORNING_BRIEF_BODY
    capture_pos = RUN_MORNING_BRIEF_BODY.index('run_batch 3 "Morning brief"')
    helper_pos = RUN_MORNING_BRIEF_BODY.index("brief_output.py")
    assert capture_pos < helper_pos


def test_run_morning_brief_still_runs_daily_note_batch():
    assert 'run_batch "3b" "Daily note"' in RUN_MORNING_BRIEF_BODY


# --- call sites: batch "3", workflow phase 4, and "all" all use the helper --

def test_all_morning_brief_call_sites_use_the_shared_function():
    call_sites = re.findall(r'^\s*run_morning_brief\s*$', SOURCE, re.MULTILINE)
    assert len(call_sites) == 3, (
        "Expected exactly 3 call sites (batch case '3', 'workflow', 'all'), "
        f"found {len(call_sites)}"
    )


def test_no_call_site_still_calls_run_batch_3_directly():
    """A regression that reintroduces a direct, unhardened
    `run_batch 3 "Morning brief" ...` call outside run_morning_brief would
    silently restore --dangerously-skip-permissions for that path."""
    direct_calls = re.findall(r'^\s*run_batch 3 "Morning brief"[^\n]*', SOURCE, re.MULTILINE)
    assert len(direct_calls) == 1, direct_calls  # only inside run_morning_brief
    assert direct_calls[0] in RUN_MORNING_BRIEF_BODY
