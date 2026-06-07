# Memory System - Architecture

Larry's memory system. Three layers that work together: file-based memories (MEMORY.md), semantic memory (MemPalace/Milla), and active context. Persistent across sessions - making Larry a genuine second brain.

**One memory, in the vault.** Claude Code's auto-memory and the vault/Milla memory used to live as two parallel tracks with different frontmatter, which drifted and contradicted each other over time. They have been converged into a single store inside the vault - see [Memory Convergence](#memory-convergence) below.

---

## Layer 1: File-Based Memories (MEMORY.md)

### Filesystem

Claude Code's auto-memory is redirected into the vault via `autoMemoryDirectory` in `.claude/settings.json`, so there is exactly one memory store and no competing copy under `~/.claude`:

```jsonc
// .claude/settings.json
{ "autoMemoryDirectory": "{{VAULT_PATH}}/memory" }
```

```
{{VAULT_PATH}}/memory/        ← inside the vault (gitignored: may hold private layers)
├── MEMORY.md          ← Master index: all memories linked here
├── user/              ← Facts about the user
├── feedback/          ← Learned preferences and behavioral rules
├── project/           ← Active project memories
└── reference/         ← Technical reference memories
```

The directory is gitignored (it can contain private-layer content), and Milla indexes it locally so the whole vault - memory files included - is one searchable memory. No memory lives under `~/.claude`, and no separate memory database is allowed to compete with the vault.

### MEMORY.md - Index

The master index read at session start. Structured as:

```markdown
## user/
- [Memory title](user/filename.md) - Short description

## feedback/
- [Memory title](feedback/filename.md) - Short description

## project/
- [Memory title](project/filename.md) - Short description

## reference/
- [Memory title](reference/filename.md) - Short description
```

Each entry links to the memory file and has a one-line summary. Larry reads MEMORY.md on init and knows what's available.

### Categories

#### user/ - Facts About the User

Stable information about the person:
- Physical data and appearance
- Home address and location
- Relationships (names, context, how to communicate)
- Subscriptions and tools
- Environment descriptions (home, workspace)
- Online profiles

Updated rarely. Stable factual base.

#### feedback/ - Learned Preferences

How Larry should behave, based on corrections and feedback:
- Tool choices (e.g., always use X CLI, never Y MCP plugin)
- Communication style (e.g., no pleasantries, no goodbyes)
- Barry rules (upscale only on request, QA before download)
- Harry rules (voice selection, TTS style)
- Privacy rules (vault-first, content separation)
- Workflow rules (robust over quick, clean up temp files)

Updated every time the user corrects behavior.

#### project/ - Project Memories

Active context about ongoing projects:
- Agent ecosystem design
- Product/feature statuses
- Partnership and business contexts
- Ongoing research

Updated when project status changes.

#### reference/ - Technical References

Stable technical configuration:
- Browser setup (persistent profile, default tabs)
- Shell aliases and functions
- Email/calendar rules
- External tool configurations

---

## Memory Convergence

Two memory tracks (Claude auto-memory and vault/Milla) used to live in parallel with different frontmatter. Two formats meant inconsistent metadata, double bookkeeping, and no shared mechanism to detect when memories contradicted each other. Over months, contradictions accumulate silently - a newer feedback rule quietly replaces an older one, two rules cancel out. Convergence fixes this with one format and a normalize-then-reconcile pipeline.

### Design principles

1. **Enrich, don't replace the mechanics.** The `MEMORY.md` index, one-file-per-fact, `description` and `metadata.type` are Claude's proven strengths - kept as-is. Vault fields are layered on top.
2. **Idempotent.** Everything is safe to run repeatedly. The normalizer only touches what is missing or off-spec.
3. **KG is the source of truth for relationships.** Supersession is stored in the knowledge graph (`kg_add`/`kg_invalidate`) and mirrored into frontmatter. If a harness rewrite drops frontmatter fields, they are restored from KG + git.
4. **Never forget.** Superseded memories are not deleted. They are marked `status: superseded`, linked to their successor, and stop surfacing in context - but remain available historically and in `as_of` queries.

### Normalization - SessionStart + nightly

A `memory_normalize.py` enriches each memory file to the superset, deriving any missing field (`created` from `git log --diff-filter=A`, `tags` from `metadata.type`, `status: active`, a privacy class, empty conflict defaults) and never touching Claude's own fields.

- **Primary trigger:** the SessionStart hook (`startup|clear|resume`) runs it over the whole memory folder at every session boundary. It fires exactly once per boundary, as part of init, so the user never has to end a session for memories to be normalized.
- **Why not the Stop hook:** Stop fires every turn (not at session end) and ignores its matcher, so it would run dozens of times per session. SessionStart fires once per boundary.
- **Safety net:** the nightly run (a light-sleep batch) calls the same script idempotently, catching memories written mid-session during a long run with no `/clear`.
- **Performance:** normalization is cheap (frontmatter scan + enrich-what's-missing). The expensive LLM conflict scan runs only at night, never at SessionStart, so init stays fast.

### Conflict reconciliation - nightly only

`memory_conflict_scan.py` detects contradictions across the normative layers (`metadata.type` in `{feedback, user, project, reference}` + KG facts; never diary/daily-notes, which don't contradict harmfully).

```
candidate pairs (Milla embeddings, high similarity)
    --> contradiction judgement (LLM): duplicate | supersession | contradiction | complementary
        ├── duplicate / supersession --> auto-resolve: older → status=superseded, link, kg_invalidate
        ├── contradiction (no clear winner) --> flag: conflict_status=flagged, notify the user, wait
        └── complementary --> no action (false alarm)
```

| Case | Action | Information preserved? |
|------|--------|------------------------|
| Duplicate | Merge into newest, older → superseded | Yes (superseded, history) |
| Supersession | Older → superseded, linked | Yes |
| Contradiction | Flagged, user decides, untouched until then | Yes |
| Complementary | No action | Yes |

Auto-resolved cases are logged but not escalated (acting on the obvious). Only genuine contradictions are surfaced to the user. Reconciliation only changes *what surfaces in context now*, never *what is stored* - identical to the KG `invalidate` + `as_of` model. A report is written to the inbox only when something changed or was flagged - never cry wolf about a clean state.

### Usage-driven curation ("dreaming") - nightly only

Conflict reconciliation curates on *content* (duplicates, contradictions). The dreaming layer adds the dimension content analysis cannot see: **which memories actually get used**. The name nods to Anthropic's Managed Agents "Dreaming" feature - a scheduled process that reviews sessions and curates memory on evidence - which this scaffold implements locally with two scripts and a prompt section.

```
Read tool call                      nightly, pre-collect before the memory batch
    --> PostToolUse hook                --> memory_usage_curate.py (no LLM)
        memory_usage_tracker.py             aggregates HOT / COLD / FRESH
        appends .usage/usage.jsonl          rotates the log (90d)
                                            writes a PRIVATE report
                                                --> the LLM memory batch weighs it in
```

- **Tracker** (`scripts/memory_usage_tracker.py`): a `PostToolUse` hook on `Read`. Logs only files under the memory dir; always exits 0; swallows every error - a broken log must never block a Read. `MEMORY.md`/`USER.md` are excluded: they are harness-loaded at init, so logging them measures nothing.
- **Curator** (`scripts/memory_usage_curate.py`): deterministic aggregation. HOT = read within 30 days. COLD = zero reads and older than a 30-day grace window (fresh files are never judged). The grace window matters: right after a bulk normalization every file looks new, so evidence has to accumulate before anything is classified cold.
- **Synthesis** (the nightly memory batch prompt): HOT memories get their `MEMORY.md` one-liner sharpened; COLD memories get their *index line* moved to an archive section that is not loaded at init - the memory file itself is never touched and never deleted. Cap the moves (e.g. 5 per night) so one bad report cannot gut the index.

**Privacy rule:** the report contains memory *file names*, and names can leak sensitive topics. Write it to a private, non-synced location - never the shared inbox - and let the nightly batch report only counts, not names, in anything public.

### Privacy classification

Privacy cannot be guessed perfectly by machine. New memories default to `privacy: 2`; a keyword pass escalates to 3/4 for sensitive categories (NSFW terms, sensitive negotiations, personal finance, health, relationships). The gatekeeper agent reviews every escalation before it is written. The memory folder is gitignored regardless, so the `privacy` field drives retrieval and metadata consistency - the leak protection itself lives in gitignore + the gatekeeper.

### MEMORY.md maintenance

The index line for each memory is kept in sync by the normalizer: superseded memories move to a `## superseded/` section at the bottom (kept, but not surfaced at the top); new memories get their pointer line.

---

## Layer 2: Semantic Memory (MemPalace / Milla)

MemPalace provides meaning-based search over the entire vault. Instead of text-matching with grep, Larry can search by meaning - "why did we change the auth flow?" finds relevant context even if those exact words never appear.

**MCP server** - 19 tools available in Claude Code. See [mempalace-setup.md](mempalace-setup.md) for installation.

### Search Rules

**MANDATORY: `mempalace_search` BEFORE Glob/Grep** for open-ended questions. Glob/Grep = only for exact searches (filenames, function names, literal strings).

**Room strategy:** The `daily` room is automatically excluded from semantic search. Use `room="daily"` explicitly ONLY for timeline questions ("what happened on X?", "what did we work on last week?").

**Fallback flow** for unknown persons/topics:
1. `mempalace_search` - no hit
2. Glob/Grep vault - no/thin hit
3. WebSearch - look up the person/topic
4. Create note in `01-personal/` (person) or `04-knowledge/` (topic)
5. Tell user what was saved

### Graph Navigation

For deeper exploration beyond simple search:

| Tool | When to use |
|------|------------|
| `mempalace_traverse` | Exploring a topic - see side context and connections. Max 2 hops normally, 3 for broad research. |
| `mempalace_find_tunnels` | Cross-domain questions - "how does X connect to Y?" Returns bridge rooms between two wings. |
| `mempalace_list_rooms` | Orientation - "what topics exist in area X?" |
| `mempalace_get_taxonomy` | Full palace structure overview. |

### Knowledge Graph (KG)

KG is Milla's long-term factual memory. Stored as subject-predicate-object triples.

**Principle:** If you don't update KG when facts change, Milla forgets. Update immediately, in the session it happens.

#### Mandatory triggers - run `kg_add` immediately:

| Event | Subject | Predicate | Object |
|-------|---------|-----------|--------|
| Barry generates image | `Barry` | `counter_is` | `<new number>` |
| Project changes status | `ProjectName` | `version_is` | `v1.0 live` |
| New person mentioned | `PersonName` | `role_is` / `relation_to` | description |
| User mentions new preference | `{{USERNAME}}` | `preference_is` | description |
| Project ends/paused | invalidate old, add new | `status_is` | `archived` / `paused` |
| Deadlines change | `ProjectName` | `deadline_is` | new date |
| New blocker arises | `ProjectName` | `blocker_is` | description |

#### Flow on fact change:
1. `mempalace_kg_query(entity)` - check what already exists
2. `mempalace_kg_invalidate(triple_id)` - invalidate old fact if exists
3. `mempalace_kg_add(subject, predicate, object)` - add new

**Rule:** `mempalace_kg_query` ALWAYS before asserting anything about an entity. Never guess - verify.

#### Session-init KG sync (Step 1b):
After hook runs - check if `00-inbox/kg-updates-*.md` exists (created by night shift). If yes: read and apply the suggested `kg_add`/`kg_invalidate` calls.

### Diary (Session Continuity)

The diary bridges sessions - what happened last time, what was decided, what's pending.

- **`mempalace_diary_read`** - Run at session init (Step 2 in CLAUDE.md). Always read 5 most recent entries.
- **`mempalace_diary_write`** - Run when session ends OR after a large task. Format: AAAK compressed.
  - Example: `SESSION:2026-04-09|USR.asked:milla.integration|implemented.diary+kg+traverse|+++`
- Never write diary mid-task - only at natural completion points.

### Indexing

| Agent | Integration |
|-------|-----------|
| **Larry** | MCP server (19 tools) + CLAUDE.md search rules |
| **Barry** | Pre-generation search + post-generation indexing |
| **Harry** | STT transcript indexing after transcription |
| **Night shift** | `mempalace mine` incrementally every night (step 0) |

**Check duplicates:** Always run `mempalace_check_duplicate` before manual `mempalace_add_drawer`.
**Re-mine:** `python -m mempalace mine "{{VAULT_PATH}}"` when needed.

---

## Layer 3: Active Context

### _active-context.md

Different from MEMORY.md: `_active-context.md` is the **current session status** - what's happening right now, blockers, what was done last.

Updated by Larry at the end of each session (or when status changes).

---

## Layer 4: Session Logs & Dreaming

Session logs capture the full conversation transcript -- every turn, tool call, and reasoning step. This is the raw material for dreaming.

### Session Logger

A PostToolUse Stop hook that exports the complete CLI session transcript at session end.

```
Session ends (Stop hook)
  --> claude sessions list --format json (find active session)
  --> claude sessions export <id> --format json (dump transcript)
  --> _private/session-logs/YYYY-MM-DD-HHmm.jsonl
```

**Format:** One JSON line per turn with role, content, tool_calls, timestamp.

**Privacy:** L4 (gitignored). Retention: 30 days.

### Dreaming (Nattskift batch 8)

Dreaming is scheduled batch processing between sessions -- analogous to biological memory consolidation during sleep. A dream reads session logs and produces curated, cross-session insights.

Inspired by Anthropic's Managed Agents dreaming architecture (Code with Claude 2026).

```
_private/session-logs/*.jsonl    (raw session transcripts)
eval-gate.jsonl                  (violation patterns)
nattrapport-feedback-audit.md    (HOT 10 + broken rules)
         |
         v
  Dream batch (Sonnet, 05:00)
         |
         v
00-inbox/nattrapport-dream-YYYY-MM-DD.md
```

**Dream report sections:**
1. Recurring mistakes across sessions
2. Converging workflows worth codifying
3. Feedback candidates (new rules from observed patterns)
4. Session statistics (count, length, tool usage, eval-gate violation rate)
5. Memory suggestions (KG/feedback entries to create)

**Three-layer memory hierarchy** (mirrors Anthropic's architecture):
1. Raw session logs -- unprocessed interaction data
2. Session-level memory writes -- local, noisy (diary, KG updates)
3. Dream-curated knowledge -- compressed, deduplicated, enriched

### KG Snapshots

Daily point-in-time export of the knowledge graph state, taken before nattskift runs.

**Output:** `_private/kg-snapshots/YYYY-MM-DD.json`

**Format:** All active triples as JSON with subject, predicate, object, valid_from, confidence.

**Retention:** 30 days. Enables rollback and drift detection.

### Eval Gate

Deterministic rule engine that evaluates agent output before delivery. Catches feedback-rule violations in real-time instead of post-hoc.

**Rules:** YAML-based (same pattern as Parry's `parry-rules.yaml`). Covers privacy leaks, emoji/em-dash, pleasantries, bro-swedish, cross-contamination.

**Agents:** Larry CLI (Stop hook), Larry-Bot (pre-send), Barry (post-QA), Harry (STT + TTS).

**Audit:** Violations logged to `eval-gate.jsonl` for nattskift dream batch consumption.

---

## How the Layers Work Together

| Layer | Purpose | Technology | Access |
|-------|---------|------------|--------|
| **MEMORY.md** | Curated, structured memories (user prefs, feedback, project state) | Markdown files | Automatic at session start |
| **MemPalace** | Semantic retrieval over entire vault + KG facts + diary continuity | ChromaDB + ONNX embeddings + MCP | 19 tools in Claude Code |
| **_active-context.md** | Working memory -- current session state | Markdown file | Read at session start (hook) |
| **Session logs** | Raw conversation transcripts for dreaming | JSONL files | Consumed by dream batch |
| **Eval Gate** | Real-time output quality enforcement | YAML rules + audit log | Inline in each agent |
| **Vault** | All other knowledge | Markdown files | Search when needed |

- MEMORY.md for precise, curated knowledge
- MemPalace for broad semantic search when you don't know which file has what you need
- KG for factual assertions that must stay current
- Diary for session-to-session continuity
- Session logs for cross-session pattern analysis (dreaming)
- Eval Gate for real-time feedback enforcement
- _active-context.md for "what am I doing right now"

---

## How Memories Are Created

1. User corrects Larry's behavior -> Larry creates feedback memory
2. Larry observes a fact about the user -> Larry creates user memory (careful with L4)
3. New project status -> Larry updates project memory
4. New technical configuration -> Larry creates reference memory
5. Fact changes -> Larry updates KG (query, invalidate, add)
6. Session ends -> Larry writes diary entry
7. Larry always updates MEMORY.md index

**Memory file format (superset):**

Each memory file carries a superset of Claude's native fields (`name`/`description`/`metadata.type`) and the vault convention (`tags`/`status`/`created`/`privacy`), plus conflict-tracking fields. Claude's YAML parser ignores keys it doesn't know, so the extra fields never break auto-memory loading.

```markdown
---
name: feedback_no_emojis              # Claude - slug, unchanged
description: Never emojis/em-dash...  # Claude - used for recall relevance
created: 2026-04-15                   # vault - derived from git first-commit / mtime
updated: 2026-06-02                   # vault
status: active                        # vault - active | superseded | archived
privacy: 2                            # vault - 1-4
tags: [memory/feedback]               # vault - derived from metadata.type
metadata:
  type: feedback                      # Claude - user | feedback | project | reference
  supersedes: []                      # slugs this memory replaces
  superseded_by: null                 # slug that replaced this one
  conflict_status: clean              # clean | flagged | resolved
---

The fact itself, in one file. Link related memories with [[other-name]].
```

Never hand-write memory files in only one of the two formats - normalization (below) keeps every file at the superset. `tags` is derived from `metadata.type` (`feedback`→`[memory/feedback]`, etc.); topic tags may be added but the type tag is mandatory.

---

## Privacy in Memories

- `user/` and `feedback/` may contain L2-3 information (personal)
- L4 content (unconscious, deeply personal) stored with extra care
- Memories never referenced in output that could leave the vault
- Feedback memories about NSFW behavior: privacy 3

---

## Implementation Notes

- Memory files are plain markdown - no special format required
- Larry creates and updates them via normal file write operations
- MEMORY.md must be kept in sync with actual memory files
- Stale memories should be archived or updated, not left outdated
- User can request memory cleanup: "clean up old memories"
