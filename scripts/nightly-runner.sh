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

# Model — read from config, never hardcoded
MODEL="${LARRY_MODEL:-claude-opus-4-8}"
NIGHTLY_MODEL="${LARRY_NIGHTLY_MODEL:-$MODEL}"

VAULT="${VAULT_PATH:?VAULT_PATH must be set}"
NIGHTLY_DIR="$VAULT/03-projects/ml-brainclone/operations/nattskift"
PROMPT_DIR="$NIGHTLY_DIR/prompts"
LOG_DIR="$NIGHTLY_DIR/logs"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/nightly-$TIMESTAMP.log"

log() {
    echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOGFILE"
}

run_batch() {
    local batch_num="$1"
    local batch_name="$2"
    local prompt_file="$PROMPT_DIR/$3"
    local effort="${4:-high}"

    if [ ! -f "$prompt_file" ]; then
        log "ERROR: Prompt file missing: $prompt_file"
        return 1
    fi

    log "=== Starting Batch $batch_num: $batch_name (effort=$effort) ==="

    local prompt_content
    prompt_content=$(cat "$prompt_file")

    if echo "$prompt_content" | claude --print \
        --dangerously-skip-permissions \
        --model "$NIGHTLY_MODEL" \
        --effort "$effort" \
        --fallback-model "$MODEL" \
        --max-turns 30 \
        >> "$LOGFILE" 2>&1; then
        log "=== Batch $batch_num DONE ==="
    else
        local exit_code=$?
        log "=== Batch $batch_num FAILED (exit code: $exit_code) ==="
        return 1
    fi
}

run_workflow() {
    local workflow_name="$1"
    local prompt_file="$PROMPT_DIR/$2"
    local effort="${3:-max}"
    local max_turns="${4:-100}"

    if [ ! -f "$prompt_file" ]; then
        log "ERROR: Workflow prompt file missing: $prompt_file"
        return 1
    fi

    log "=== Starting Workflow: $workflow_name (effort=$effort, max-turns=$max_turns) ==="

    local prompt_content
    prompt_content=$(cat "$prompt_file")

    if echo "$prompt_content" | claude --print \
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

# Step 0: Semantic memory — incremental indexing (new/changed files)
# Timeout 300s (5 min) — prevents a hung database operation from killing
# the entire batch.
#
# CRITICAL: Kill the MCP singleton before mine. The singleton holds
# ChromaDB's HNSW index open via PersistentClient. Without killing it,
# mine deadlocks on the exclusive lock. The singleton restarts
# automatically on the next MCP call.
log "--- Step 0a: Memory indexing (incremental) ---"
SINGLETON_PIDS=$(pgrep -f "mempalace-singleton" 2>/dev/null || true)
if [ -n "$SINGLETON_PIDS" ]; then
    log "--- Killing mempalace-singleton (pids: $SINGLETON_PIDS) for DB access ---"
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
    if timeout 420 python3 "$SOCIAL_SCAN" >> "$LOGFILE" 2>&1; then
        log "--- Social scan done ---"
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
        run_batch 1 "Vault hygiene" "batch1-vault-hygiene.md"
        ;;
    2)
        run_batch 2 "Inbox triage" "batch2-inbox-triage.md"
        ;;
    3)
        run_batch 3 "Morning brief" "batch3-morning-brief.md" "xhigh"
        run_batch "3b" "Daily note" "batch3b-daily-note.md" || true
        ;;
    4)
        run_batch 4 "Reddit scan" "batch4-reddit.md"
        ;;
    5)
        run_batch 5 "Distillation" "batch5-distillation.md" "xhigh"
        ;;
    6)
        run_batch 6 "KG hygiene" "batch6-kg-hygiene.md" "xhigh"
        log "--- Batch 6b: Automatic KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true
        ;;
    7)
        log "--- Batch 7 pre-collect: feedback audit ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true
        run_batch 7 "Feedback audit" "batch7-feedback-audit.md"
        ;;
    8)
        run_batch 8 "Stuck feedback" "batch8-stuck-feedback.md"
        ;;
    workflow)
        log "Running nightly in workflow mode (Dynamic Workflows)..."
        log "Step 0a-0f (data) -> Phase 1 (pre-collect) -> Phase 2 (parallel) -> Phase 3 (KG) -> Phase 4 (brief)"

        # Phase 1: Feedback audit pre-collect (Python, needed by the workflow)
        log "--- Phase 1: Feedback pre-collect ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true

        # Phase 2: Parallel analysis (batch 1+2+6+7+8 parallel, then 5 sequential)
        # ONE Claude call with Dynamic Workflows, effort=max, 100 turns
        log "--- Phase 2: Parallel analysis (Dynamic Workflows) ---"
        run_workflow "Parallel analysis" "workflow-parallel-analysis.md" "max" "100" || true

        # Phase 3: KG extraction (Python, needs batch 6 output from the workflow)
        log "--- Phase 3: KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true

        # Phase 4: Morning brief (Claude CLI, ALWAYS LAST — summarizes everything)
        # Reddit data already collected in step 0e (social-scan.py -> .data/social-scan.txt)
        log "--- Phase 4: Morning brief ---"
        run_batch 3 "Morning brief" "batch3-morning-brief.md" "xhigh" || true
        run_batch "3b" "Daily note" "batch3b-daily-note.md" || true
        ;;
    all)
        log "Running all batches in sequence (legacy mode)..."
        run_batch 1 "Vault hygiene" "batch1-vault-hygiene.md" || true
        run_batch 2 "Inbox triage" "batch2-inbox-triage.md" || true
        run_batch 5 "Distillation" "batch5-distillation.md" "xhigh" || true
        run_batch 6 "KG hygiene" "batch6-kg-hygiene.md" "xhigh" || true
        log "--- Batch 6b: Automatic KG extraction ---"
        KG_EXTRACT="$NIGHTLY_DIR/palace-kg-extract.py"
        [ -f "$KG_EXTRACT" ] && python3 "$KG_EXTRACT" >> "$LOGFILE" 2>&1 || true
        log "--- Batch 7 pre-collect: feedback audit ---"
        FA_COLLECT="$NIGHTLY_DIR/feedback-audit-collect.py"
        [ -f "$FA_COLLECT" ] && python3 "$FA_COLLECT" >> "$LOGFILE" 2>&1 || true
        run_batch 7 "Feedback audit" "batch7-feedback-audit.md" || true
        run_batch 8 "Stuck feedback" "batch8-stuck-feedback.md" || true
        run_batch 3 "Morning brief" "batch3-morning-brief.md" "xhigh" || true
        run_batch "3b" "Daily note" "batch3b-daily-note.md" || true
        ;;
    *)
        log "Unknown batch number: $BATCH"
        log "Usage: $0 [1|2|3|4|5|6|7|8|all|workflow]"
        exit 1
        ;;
esac

log "====================================================="
log "Nightly run complete — $(date +%H:%M:%S)"
log "Logfile: $LOGFILE"
log "====================================================="
