# Feedback Loop — Automated Mistake Detection

A nightly batch that turns accumulated user corrections into a prioritized, living "don't repeat this" list injected at session start.

Inspired by Dave Killeen's Dex pattern (mistakes.md injected via hooks), adapted for a multi-agent vault architecture with existing feedback memory infrastructure.

---

## Problem

Over time, your system accumulates hundreds of feedback memories (user corrections, style preferences, workflow rules). They all live in flat memory files with equal weight. Session init loads them all — but a feedback rule created two months ago about date formatting has the same priority as a critical privacy rule created yesterday.

Without prioritization, the most important rules get buried. Without automated detection, the same mistakes recur because the feedback loop is purely reactive (user corrects → memory saved).

---

## Architecture

Three components. No new daemons.

```
┌──────────────────────────────────────────────────────────┐
│                    NIGHTLY BATCH                          │
│                                                          │
│  1. Python collector reads feedback/* files               │
│     → .data/feedback-items.txt (condensed)               │
│                                                          │
│  2. Python collector reads recent nattrapport-*.md       │
│     → .data/recent-nattrapporter.txt                     │
│                                                          │
│  3. Claude batch cross-references rules vs. reports      │
│     → Detects violations, categorizes, scores severity   │
│     → Updates _private/feedback-tracker.json             │
│     → Writes 00-inbox/nattrapport-feedback-audit.md      │
│                                                          │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                   SESSION INIT                            │
│                                                          │
│  Step 2e: Read HOT 10 from nattrapport-feedback-audit.md │
│  → Prioritized rules active in working memory            │
│  → Silent report: "(Feedback: N hot, M broken)"         │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Component 1 — Collector (Python)

`feedback-audit-collect.py` runs before the Claude batch. It:

- Reads all `memory/feedback/*.md` files
- Parses frontmatter (name, description, type) and first paragraph
- Loads or initializes `_private/feedback-tracker.json`
- Registers new items in the tracker (severity/category filled by Claude later)
- Collects nattrapport files from last 3 days
- Writes condensed `.data/` files for Claude consumption

This keeps the Claude batch focused on analysis, not file-system traversal.

### Component 2 — Claude Batch (Nattskift Prompt)

The batch prompt reads the pre-collected data and:

**Cross-references:** For each feedback rule, scans nattrapport text for violation signals. Example: feedback says "always use GWS CLI for mail" + nattrapport shows MCP mail calls → violation detected.

**Categorizes** each rule:
- `communication` — tone, language, style
- `technical` — tools, APIs, infrastructure
- `privacy` — data layers, access control
- `workflow` — process, ordering, priorities
- `identity` — persona, creative ownership, relationships

**Scores severity** (1-3):
- 3 = Direct harm (privacy leak, wrong external communication, data loss)
- 2 = Time waste or irritation (wrong tool, bad tone, unnecessary questions)
- 1 = Style preference (spelling, formatting, word choice)

**Updates tracker:** Bumps `trigger_count` for violated rules, timestamps `last_seen`.

**Generates report** with four sections:
- **HOT 10** — Top 10 rules by severity DESC, trigger_count DESC
- **BROKEN** — Rules violated in recent nattrapport evidence
- **CANDIDATES** — New patterns not yet formalized as feedback rules
- **STALE** — Rules referencing obsolete tools, duplicating others, or never triggered

### Component 3 — Feedback Tracker (JSON)

`_private/feedback-tracker.json` — persistent state across nightly runs:

```json
{
  "version": 1,
  "last_audit": "2026-05-05",
  "items": {
    "feedback_no_cigars": {
      "severity": 1,
      "trigger_count": 0,
      "last_seen": "",
      "category": "identity"
    },
    "feedback_privacy_awareness": {
      "severity": 3,
      "trigger_count": 2,
      "last_seen": "2026-05-04",
      "category": "privacy"
    }
  }
}
```

---

## Scheduling

Runs after KG hygiene, before morning brief:

| Batch | Time | Purpose |
|-------|------|---------|
| ... | 04:00 | KG hygiene |
| **Feedback audit** | **04:30** | **Cross-reference + prioritize** |
| Morning brief | 06:00 | Summary (can reference audit) |

In the `all` sequence of the nightly runner:
1. Python collector runs first (fast, <10s)
2. Claude batch runs second (analysis, ~2-5 min)

---

## Session Init Integration

Add to your CLAUDE.md session init sequence:

```markdown
### Step 2e — Hot mistakes
If `00-inbox/nattrapport-feedback-audit.md` exists: read the HOT 10 section.
These are the prioritized feedback rules — keep them active in working memory.
Report silently: `(Feedback: N hot, M broken)`.
```

---

## Real-Time Complement: Eval Gate

The nightly feedback audit catches patterns post-hoc. The **eval gate** catches violations in real-time, before output reaches the user.

```
Agent output
  --> eval_gate.evaluate(text, agent)
  --> Check against eval-rules.yaml (compiled feedback rules)
  --> verdict: pass / flag / block
  --> If violation: log to eval-gate.jsonl + warn (stderr/log)
```

**Shared module:** `eval/eval_gate.py` -- deterministic rule engine (no LLM). Loads YAML rules with hot-reload via mtime check.

**Agents integrated:**
| Agent | Hook point | Behavior |
|-------|-----------|----------|
| Larry CLI | PostToolUse Stop hook | Flags to stderr, never blocks |
| Larry-Bot | After `_larry_reply()`, before `_send()` | Log warning |
| Barry | After QA, before metadata | Print warning |
| Harry | Before TTS + after STT | Print to stderr |

**Rule format** (same pattern as `parry-rules.yaml`):
```yaml
- id: no_emoji
  description: Inga emojis i output
  pattern: "[\\U0001F600-\\U0001F9FF]"
  match_type: regex
  severity: flag
  agents: [larry-cli, larry-bot, barry, harry]
```

**Audit trail:** Violations logged to `eval-gate.jsonl` -- consumed by nattskift dream batch (batch 8) for cross-session pattern analysis.

The nightly audit and eval gate are complementary:
- **Eval gate** = real-time, deterministic, catches known patterns as they happen
- **Nightly audit** = batch, LLM-powered, discovers new patterns and prioritizes

---

## Cross-Session Analysis: Dream Batch

The **dream batch** (nattskift batch 8) reads session transcripts and eval-gate violations to find patterns that span multiple sessions.

**Input:** Session logs + `eval-gate.jsonl` + nattrapport-feedback-audit + existing feedback files.

**Output:** `00-inbox/nattrapport-dream-YYYY-MM-DD.md` with:
1. Recurring mistakes across sessions
2. Converging workflows worth codifying
3. Feedback candidates (new rules)
4. Session statistics and eval-gate violation trends
5. Memory suggestions (KG/feedback entries to create)

See [memory-system.md](memory-system.md) Layer 4 for full dreaming architecture.

---

## Scaling

The collector handles 150+ feedback files in <1 second. The Claude batch processes the condensed summary, not raw files. Cost is one Haiku/Sonnet call per night (~$0.01-0.05).

As feedback files grow beyond 200, the STALE section becomes increasingly valuable -- it identifies rules to merge or archive, keeping the active set manageable.
