#!/bin/bash
# =============================================================================
# Larry Nightly — Batch Runner
# =============================================================================
# Runs nightly batch jobs: bash scripts collect data, Claude CLI (Opus) writes
# reports. Triggered by Windows Task Scheduler or manually.
#
# Usage:
#   ./nightly-runner.sh [batch-number]
#   ./nightly-runner.sh 1         # Batch 1 (vault hygiene)
#   ./nightly-runner.sh 2         # Batch 2 (inbox triage)
#   ./nightly-runner.sh 3         # Batch 3 (morning brief) + 3b (daily note)
#   ./nightly-runner.sh 4         # Batch 4 (reddit, legacy — now part of social-scan)
#   ./nightly-runner.sh 5         # Batch 5 (distillation)
#   ./nightly-runner.sh 6         # Batch 6 (KG hygiene)
#   ./nightly-runner.sh 7         # Batch 7 (feedback audit)
#   ./nightly-runner.sh 8         # Batch 8 (stuck feedback)
#   ./nightly-runner.sh all       # All batches in sequence (legacy)
#   ./nightly-runner.sh workflow  # Dynamic Workflows (parallel + sequential)
#   ./nightly-runner.sh           # Default: workflow
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# PATH hardening (defense-in-depth)
# -----------------------------------------------------------------------------
# Task Scheduler runs bash --login. If profile loading fails or the env is
# stripped — make sure all binaries we call are still found.
#
# CRITICAL: On Windows, WindowsApps contains a WSL bash shim that hijacks
# `bash` calls. Git Bash's /usr/bin MUST come first. WindowsApps removed.
export PATH="/usr/bin:$HOME/.local/bin:/c/Program Files/nodejs:/c/Program Files/Git/bin:$PATH"
export PYTHONIOENCODING=utf-8

# Model and effort -- read from config, never hardcoded. Medium is the baseline:
# value per token decides. High when medium gets stuck, max only when high does
# not reach. Never xhigh or max by habit: a night of max costs several times more
# and is slower for no visible gain.
MODEL="${LARRY_MODEL:-opus}"
NIGHTLY_MODEL="${LARRY_NIGHTLY_MODEL:-$MODEL}"
NIGHTLY_EFFORT="${LARRY_NIGHTLY_EFFORT:-medium}"

# Long-lived subscription token (`claude setup-token`, valid a year, never
# refreshed). With CLAUDE_CODE_OAUTH_TOKEN set the CLI never touches the shared
# credentials file or its refresh lock, so the night shift cannot race the
# owner's open sessions over a token refresh. The file holds the token only.
# Missing file: the shared credentials are used as before.
TOKEN_FILE="${CLAUDE_NIGHTLY_TOKEN_FILE:-$HOME/.config/claude/nightly-token}"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -s "$TOKEN_FILE" ]; then
    CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    export CLAUDE_CODE_OAUTH_TOKEN
fi

# A fast failure is infrastructure, not the model. One night four batches fell
# after 10-17 s each on "Failed to refresh OAuth token: another Claude Code
# process is refreshing it". A slow failure (the model worked and fell) is not rerun.
CLAUDE_FAST_FAIL_S=60
CLAUDE_RETRY_WAIT_S=90

VAULT="${VAULT_PATH:?VAULT_PATH must be set}"
NIGHTLY_DIR="$VAULT/03-projects/ml-brainclone/operations/nattskift"
PROMPT_DIR="$NIGHTLY_DIR/prompts"
DATA_DIR="$NIGHTLY_DIR/.data"
LOG_DIR="$NIGHTLY_DIR/logs"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

# Directory this script lives in — brief_output.py and collect-calendar.py
# ship next to it (see docs/security-untrusted-input.md).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$LOG_DIR" "$DATA_DIR"

LOGFILE="$LOG_DIR/nightly-$TIMESTAMP.log"

log() {
    echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOGFILE"
}

# claude with one retry when the call dies fast. The prompt comes in CLAUDE_PROMPT,
# the caller redirects stdout as before.
claude_retry() {
    local attempt rc start took
    for attempt in 1 2; do
        start=$(date +%s); rc=0
        printf '%s' "$CLAUDE_PROMPT" | claude "$@" || rc=$?
        took=$(( $(date +%s) - start ))
        if [ "$rc" -eq 0 ]; then return 0; fi
        if [ "$took" -ge "$CLAUDE_FAST_FAIL_S" ] || [ "$attempt" -eq 2 ]; then return "$rc"; fi
        log "--- claude fell after ${took} s (exit $rc), retry in ${CLAUDE_RETRY_WAIT_S} s ---"
        sleep "$CLAUDE_RETRY_WAIT_S"
    done
}

# Shadow steps judge beside the real thing and change nothing. A hard wall clock
# and `|| true`: a shadow must never fail the night or delay what follows.
run_shadow() {
    local label="$1" secs="$2" script="$3"; shift 3
    [ -f "$script" ] || return 0
    log "--- Shadow: $label ---"
    timeout "$secs" python3 "$script" "$@" >> "$LOGFILE" 2>&1 || log "--- Shadow $label fell or timed out (ignored) ---"
}

# Auth pre-flight. A tiny call before anything costly. Three attempts, and when
# the error is the refresh lock held by another live Claude process (a session
# left open overnight holds it for half an hour), wait it out up to
# PREFLIGHT_LOCK_WAIT_S. `|| rc=$?` keeps `set -e` from killing the script
# before the failure is logged. The answer must be a whole line "OK": a plain
# grep for OK went green on the word "token" in the error message.
PREFLIGHT_ATTEMPTS=3
PREFLIGHT_LOCK_WAIT_S=2400
PREFLIGHT_LOCK_POLL_S=120
auth_preflight() {
    local attempt=0 fails=0 waited=0 rc out
    while [ "$fails" -lt "$PREFLIGHT_ATTEMPTS" ]; do
        attempt=$((attempt + 1)); rc=0
        out=$(echo "Reply with exactly: OK" | timeout 90 claude --print --model "${LARRY_SIMPLE_MODEL:-sonnet}" --max-turns 1 2>&1) || rc=$?
        if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -qx '[[:space:]]*OK[[:space:]]*'; then
            log "--- Auth pre-flight OK (attempt $attempt) ---"; return 0
        fi
        if printf '%s' "$out" | grep -qi "refresh" && [ "$waited" -lt "$PREFLIGHT_LOCK_WAIT_S" ]; then
            log "--- Auth pre-flight: refresh lock held by another Claude process, waiting ${PREFLIGHT_LOCK_POLL_S} s ---"
            sleep "$PREFLIGHT_LOCK_POLL_S"; waited=$((waited + PREFLIGHT_LOCK_POLL_S)); continue
        fi
        fails=$((fails + 1))
        log "--- Auth pre-flight attempt $attempt fell (exit $rc, $fails/$PREFLIGHT_ATTEMPTS): ${out:0:300} ---"
        sleep 60
    done
    return 1
}

run_batch() {
    local batch_num="$1"
    local batch_name="$2"
    local prompt_file="$PROMPT_DIR/$3"
    local effort="${4:-$NIGHTLY_EFFORT}"
    # -------------------------------------------------------------------
    # Untrusted-input hardening — see docs/security-untrusted-input.md.
    #
    # A session that reads text written by strangers (social scan output:
    # X/LinkedIn/Reddit posts, mail subjects, calendar invite descriptions)
    # must not also hold tools that can act on what it read. A prompt
    # injection hiding in that text has nothing to reach if the session
    # can only read.
    #
    # restrict_readonly=true switches this call to that mode:
    #   - no --dangerously-skip-permissions
    #   - --tools Read,Glob,Grep only (no Bash, Write, Edit)
    #   - --strict-mcp-config with no --mcp-config, i.e. zero MCP servers
    #     (no Playwright/browser tools even if project or user config
    #     would otherwise attach them)
    #   - --add-dir grants read access to readonly_dirs (default: the vault
    #     and the nightly data directory) despite permissions not being
    #     bypassed. Callers that only need a narrower slice can pass a
    #     smaller readonly_dirs to keep the session's read scope tight.
    #
    # capture_file, when set, redirects the session's stdout (its answer)
    # to that file instead of letting it write output to disk directly.
    # The caller then hands the file to scripts/brief_output.py, which
    # validates it and writes the real target file atomically — a broken
    # or truncated response never overwrites a previously good one.
    #
    # Every other batch call leaves both arguments unset and gets exactly
    # the previous behavior. Do not default restrict_readonly to true.
    # -------------------------------------------------------------------
    local restrict_readonly="${5:-false}"
    local capture_file="${6:-}"
    # readonly_dirs: space-separated directories the read-only session may
    # read (via --add-dir). Sessions that do not need the whole vault should
    # get less. Defaults to the previous behavior (vault + nightly dir) so
    # every existing caller is unaffected.
    local readonly_dirs="${7:-$VAULT $NIGHTLY_DIR}"

    if [ ! -f "$prompt_file" ]; then
        log "ERROR: Prompt file missing: $prompt_file"
        return 1
    fi

    log "=== Starting Batch $batch_num: $batch_name (effort=$effort, readonly=$restrict_readonly) ==="

    local prompt_content
    prompt_content=$(cat "$prompt_file")

    # bypass: every caller that leaves restrict_readonly false needs a "# bypass:"
    # comment on its call line saying why the session needs more than reading
    # (tests/test_nightly_runner_readonly.py enforces it). No step gets full bypass by default.
    local perm_flags="--dangerously-skip-permissions"
    local tool_flags=""
    if [ "$restrict_readonly" = "true" ]; then
        perm_flags=""
        tool_flags="--tools Read,Glob,Grep --strict-mcp-config"
        local readonly_dir
        for readonly_dir in $readonly_dirs; do
            tool_flags="$tool_flags --add-dir $readonly_dir"
        done
    fi

    if [ -n "$capture_file" ]; then
        # shellcheck disable=SC2086  # perm_flags/tool_flags are intentionally
        # unquoted so an empty value expands to nothing rather than "".
        if CLAUDE_PROMPT="$prompt_content" claude_retry --print $perm_flags \
            --model "$NIGHTLY_MODEL" \
            --effort "$effort" \
            --fallback-model "$MODEL" \
            --max-turns 30 \
            $tool_flags \
            > "$capture_file" 2>>"$LOGFILE"; then
            cat "$capture_file" >> "$LOGFILE" 2>/dev/null || true
            log "=== Batch $batch_num DONE ==="
        else
            local exit_code=$?
            log "=== Batch $batch_num FAILED (exit code: $exit_code) ==="
            return 1
        fi
    else
        # shellcheck disable=SC2086
        if CLAUDE_PROMPT="$prompt_content" claude_retry --print $perm_flags \
            --model "$NIGHTLY_MODEL" \
            --effort "$effort" \
            --fallback-model "$MODEL" \
            --max-turns 30 \
            $tool_flags \
            >> "$LOGFILE" 2>&1; then
            log "=== Batch $batch_num DONE ==="
        else
            local exit_code=$?
            log "=== Batch $batch_num FAILED (exit code: $exit_code) ==="
            return 1
        fi
    fi
}

run_morning_brief() {
    # Shared by the "3", "workflow", and "all" cases below so the
    # read-only wiring lives in exactly one place.
    log "--- Calendar collection (deterministic, no LLM in the loop) ---"
    if timeout 120 python3 "$SCRIPT_DIR/collect-calendar.py" >> "$LOGFILE" 2>&1; then
        log "--- Calendar collection done ---"
    else
        log "--- Calendar collection FAILED (continuing with empty/stale calendar-today.json) ---"
    fi

    local brief_target="$VAULT/00-inbox/morning-brief-$TODAY.md"
    local brief_capture="$DATA_DIR/.batch3-stdout-$TODAY.txt"

    log "--- Morning brief compilation (read-only session, no MCP) ---"
    run_batch 3 "Morning brief" "batch3-morning-brief.md" "medium" "true" "$brief_capture" || true

    if python3 "$SCRIPT_DIR/brief_output.py" "$brief_capture" "$brief_target" >> "$LOGFILE" 2>&1; then
        log "--- Brief written: $brief_target ---"
    else
        # Validation failed: the previous valid file on disk is left
        # untouched, but the raw text is saved instead of just discarded —
        # otherwise a complete brief vanishes without a trace just because
        # it got caught in a code fence or similar. Only written when
        # capture_file actually has content.
        if [ -s "$brief_capture" ]; then
            raw_file="$DATA_DIR/morning-brief-$TODAY.raw.txt"
            cp "$brief_capture" "$raw_file" 2>>"$LOGFILE" || true
            log "--- Brief validation failed, raw text saved to $raw_file, previous file kept (see $brief_target) ---"
        else
            log "--- Brief validation failed, session produced no text, previous file kept (see $brief_target) ---"
        fi
    fi
    rm -f "$brief_capture"

    run_batch "3b" "Daily note" "batch3b-daily-note.md" || true  # bypass: writes the daily note itself, reads only the brief written above
}

run_workflow() {
    local workflow_name="$1"
    local prompt_file="$PROMPT_DIR/$2"
    local effort="${3:-$NIGHTLY_EFFORT}"
    local max_turns="${4:-100}"

    if [ ! -f "$prompt_file" ]; then
        log "ERROR: Workflow prompt file missing: $prompt_file"
        return 1
    fi

    log "=== Starting Workflow: $workflow_name (effort=$effort, max-turns=$max_turns) ==="

    local prompt_content
    prompt_content=$(cat "$prompt_file")

    if CLAUDE_PROMPT="$prompt_content" claude_retry --print \
        --dangerously-skip-permissions \
        --model "$NIGHTLY_MODEL" \
        --effort "$effort" \
        --fallback-model "$MODEL" \
        --max-turns "$max_turns" \
        >> "$LOGFILE" 2>&1; then
        log "=== Workflow $workflow_name DONE ==="
    else
        local exit_code=$?
        log "=== Workflow $workflow_name FAILED (exit code: $exit_code) ==="
        return 1
    fi
}

# =============================================================================
# Main logic
# =============================================================================

BATCH="${1:-workflow}"

log "====================================================="
log "Larry Nightly — $TODAY"
log "Batch: $BATCH"
log "====================================================="

if ! auth_preflight; then
    log "AUTH FAILED -- no batch can run. Check the token (claude setup-token) or the session."
    exit 2
fi

# Step 0: Semantic memory — incremental indexing (new/changed files)
# Timeout 300s (5 min) — prevents a hung database operation from killing
# the entire batch.
#
# CRITICAL: Kill the MCP singleton before mine. The singleton holds
# ChromaDB's HNSW index open via PersistentClient. Without killing it,
# mine deadlocks on the exclusive lock. The singleton restarts
# automatically on the next MCP call.
#
# Whoever stops the memory server gives it back. Nothing restarts it on its own
# (no watchdog runs at night), so: if it was up before, it is started again
# after the last step that touches the database, and also if the run dies in
# between (trap). If it was down before, it is left down.
log "--- Step 0a: Memory indexing (incremental) ---"
SINGLETON_PIDS=$(pgrep -f "mempalace-singleton" 2>/dev/null || true)
MEMORY_WAS_UP=false
give_memory_back() {
    if [ "$MEMORY_WAS_UP" = "true" ] && [ -n "${MEMORY_START_CMD:-}" ]; then
        MEMORY_WAS_UP=false
        if eval "$MEMORY_START_CMD" >> "$LOGFILE" 2>&1; then log "--- Memory server started again ---"
        else log "--- Memory server did NOT start again (start it by hand) ---"; fi
    fi
}
trap give_memory_back EXIT
if [ -n "$SINGLETON_PIDS" ]; then
    MEMORY_WAS_UP=true
    log "--- Stopping memory server (pids: $SINGLETON_PIDS) for DB access ---"
    echo "$SINGLETON_PIDS" | xargs kill 2>/dev/null || true
    sleep 2
fi
if timeout 300 python3 -m mempalace mine "$VAULT" >> "$LOGFILE" 2>&1; then
    log "--- Memory indexing done ---"
else
    log "--- Memory indexing FAILED (continuing anyway) ---"
fi

# Step 0b: Palace hygiene — clean stale + duplicate drawers
log "--- Step 0b: Palace hygiene (stale + dedup) ---"
if [ -f "$NIGHTLY_DIR/palace-hygiene.py" ]; then
    if timeout 300 python3 "$NIGHTLY_DIR/palace-hygiene.py" >> "$LOGFILE" 2>&1; then
        log "--- Palace hygiene done ---"
    else
        log "--- Palace hygiene FAILED (continuing anyway) ---"
    fi
fi

# Step 0c: FTS5 rebuild — full-text search index
log "--- Step 0c: FTS5 rebuild ---"
FTS5_SCRIPT="$VAULT/03-projects/ml-brainclone/search/vault_fts5_build.py"
if [ -f "$FTS5_SCRIPT" ]; then
    if timeout 120 python3 "$FTS5_SCRIPT" >> "$LOGFILE" 2>&1; then
        log "--- FTS5 rebuild done ---"
    else
        log "--- FTS5 rebuild FAILED (continuing anyway) ---"
    fi
fi

# Last step that touches the memory database: hand the server back
give_memory_back

# Step 0c2: Diary pending flush -- entries the auto-diary could not write while
# the memory server was down. Needs the server up; if it is not, the queue is
# left for the next night.
if [ -f "$SCRIPT_DIR/diary_pending_flush.py" ]; then
    log "--- Step 0c2: Diary pending flush ---"
    timeout 600 python3 "$SCRIPT_DIR/diary_pending_flush.py" --apply >> "$LOGFILE" 2>&1 \
        && log "--- Diary pending flush done ---" || log "--- Diary pending flush FAILED (continuing anyway) ---"
fi

# Step 0d: Sentiment snapshot (local GPU model)
log "--- Step 0d: Sentiment daily snapshot ---"
WARRY_CLI="$VAULT/03-projects/ml-brainclone/warry/warry_cli.py"
if [ -f "$WARRY_CLI" ]; then
    if timeout 120 python3 "$WARRY_CLI" daily >> "$LOGFILE" 2>&1; then
        log "--- Sentiment snapshot done ---"
    else
        log "--- Sentiment snapshot FAILED (continuing anyway) ---"
    fi
fi

# Step 0e: Social scan — X + LinkedIn + Reddit + Gmail + Teams via Playwright
# Produces .data/social-scan.txt (all sources, for morning brief)
# + 00-inbox/reddit-YYYY-MM-DD.md (Reddit digest, for distillation)
log "--- Step 0e: Social scan (X + LinkedIn + Reddit + Gmail + Teams) ---"
SOCIAL_SCAN="$NIGHTLY_DIR/social-scan.py"
if [ -f "$SOCIAL_SCAN" ]; then
    # 600 s: opening a dozen tabs with full page loads took 3-4 minutes and the
    # old 420 s killed the scan in the middle of its session backup.
    if timeout 600 python3 "$SOCIAL_SCAN" >> "$LOGFILE" 2>&1; then
        log "--- Social scan done ---"
    elif [ -n "$(find "$DATA_DIR/social-scan.txt" -newermt "$TODAY" 2>/dev/null)" ]; then
        # Today's output exists, it was the shutdown that fell. The step did its job.
        log "--- Social scan done (shutdown fell after the output was written) ---"
    else
        log "--- Social scan FAILED (continuing anyway) ---"
    fi
fi

# Step 0f: Daily Life Collector — passive input pipeline (weather, music, calendar, health)
log "--- Step 0f: Daily Life Collector ---"
DLC_SCRIPT="$VAULT/03-projects/ml-brainclone/collectors/daily-life-collector.py"
if [ -f "$DLC_SCRIPT" ]; then
    if timeout 120 python3 "$DLC_SCRIPT" >> "$LOGFILE" 2>&1; then
        log "--- Daily Life Collector done ---"
    else
        log "--- Daily Life Collector FAILED (continuing anyway) ---"
    fi
fi

# Step 1: Collect vault data (always, except for standalone batches)
if [ "$BATCH" != "4" ] && [ "$BATCH" != "4b" ]; then
    log "--- Step 1: Collecting vault data ---"
    if bash "$NIGHTLY_DIR/collect-vault-data.sh" >> "$LOGFILE" 2>&1; then
        log "--- Data collection done ---"
    else
        log "--- Data collection FAILED ---"
    fi
fi

# Step 2: Run batch jobs via Claude CLI (Opus)
case "$BATCH" in
    1)
        run_batch 1 "Vault hygiene" "batch1-vault-hygiene.md"  # bypass: fixes frontmatter and moves files, reads only the vault
        ;;
    2)
        run_batch 2 "Inbox triage" "batch2-inbox-triage.md"  # bypass: moves inbox files, reads only the vault
        ;;
    3)
        run_morning_brief
        ;;
    4)
        run_batch 4 "Reddit scan" "batch4-reddit.md"  # bypass: legacy, kept for manual debugging only
        ;;
    5)
        run_batch 5 "Distillation" "batch5-distillation.md"  # bypass: writes the distillate, reads only the vault
        ;;
    6)
        run_batch 6 "KG hygiene" "batch6-kg-hygiene.md"  # bypass: writes the graph update proposal, reads only key vault files
        log "--- Batch 6b: Automatic KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true
        ;;
    7)
        log "--- Batch 7 pre-collect: feedback audit ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true
        run_batch 7 "Feedback audit" "batch7-feedback-audit.md"  # bypass: writes the feedback tracker, reads only memory and collector output
        ;;
    8)
        run_batch 8 "Stuck feedback" "batch8-stuck-feedback.md"  # bypass: updates feedback files, reads only memory
        ;;
    workflow)
        log "Running nightly in workflow mode (Dynamic Workflows)..."
        log "Step 0a-0f (data) -> Phase 1 (pre-collect) -> Phase 2 (parallel) -> Phase 3 (KG) -> Phase 4 (brief)"

        # Phase 1: Feedback audit pre-collect (Python, needed by the workflow)
        log "--- Phase 1: Feedback pre-collect ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true

        # Lifecycle shadow: judges the inbox before any reaper has moved anything
        # and reports the difference against today's reapers. Moves nothing.
        run_shadow "Lifecycle" 60 "$SCRIPT_DIR/lifecycle_reaper.py" --vault "$VAULT"

        # Phase 2: Parallel analysis (batch 1+2+6+7+8 parallel, then 5 sequential)
        # ONE Claude call with Dynamic Workflows, medium effort, 100 turns
        log "--- Phase 2: Parallel analysis (Dynamic Workflows) ---"
        run_workflow "Parallel analysis" "workflow-parallel-analysis.md" "medium" "100" || true  # bypass: spawns the batches as subagents, each reads only the vault

        # Phase 3: KG extraction (Python, needs batch 6 output from the workflow)
        log "--- Phase 3: KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true

        # Phase 4: Morning brief (Claude CLI, ALWAYS LAST — summarizes everything)
        # Reddit data already collected in step 0e (social-scan.py -> .data/social-scan.txt)
        log "--- Phase 4: Morning brief ---"
        run_morning_brief
        ;;
    all)
        log "Running all batches in sequence (legacy mode)..."
        run_batch 1 "Vault hygiene" "batch1-vault-hygiene.md" || true  # bypass: fixes frontmatter and moves files, reads only the vault
        run_batch 2 "Inbox triage" "batch2-inbox-triage.md" || true  # bypass: moves inbox files, reads only the vault
        run_batch 5 "Distillation" "batch5-distillation.md" || true  # bypass: writes the distillate, reads only the vault
        run_batch 6 "KG hygiene" "batch6-kg-hygiene.md" || true  # bypass: writes the graph update proposal, reads only key vault files
        log "--- Batch 6b: Automatic KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true
        log "--- Batch 7 pre-collect: feedback audit ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true
        run_batch 7 "Feedback audit" "batch7-feedback-audit.md" || true  # bypass: writes the feedback tracker, reads only memory and collector output
        run_batch 8 "Stuck feedback" "batch8-stuck-feedback.md" || true  # bypass: updates feedback files, reads only memory
        run_morning_brief
        ;;
    *)
        log "Unknown batch number: $BATCH"
        log "Usage: $0 [1|2|3|4|5|6|7|8|all|workflow]"
        exit 1
        ;;
esac

# Foreman shadow, last: a cheap model reads the night's batch transcripts
# afterwards and judges each checkpoint (stuck, off track, done, needs a human).
# Steers nothing; it collects verdicts to calibrate against before it may.
run_shadow "Foreman" 300 "$SCRIPT_DIR/foreman_shadow.py" run --days 1

log "====================================================="
log "Nightly run complete — $(date +%H:%M:%S)"
log "Logfile: $LOGFILE"
log "====================================================="
