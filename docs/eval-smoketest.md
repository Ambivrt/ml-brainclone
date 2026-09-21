# Larry Smoketest — regression check on model swap

A lightweight, manual evaluation pattern for catching regressions in Larry's core services when you upgrade the underlying model or change `CLAUDE.md`. Inspired by [carlini/yet-another-applied-llm-benchmark](https://github.com/carlini/yet-another-applied-llm-benchmark) but distilled to a markdown checklist — no DSL, no Docker, no CI. Runs in ~15 minutes.

---

## Why this exists

Your Larry stack depends on the LLM respecting the invariants you've codified in `CLAUDE.md`, memory files, and the Ten Commandments. When Anthropic ships a new Claude version — or when you refactor `CLAUDE.md` — any of those invariants can silently regress. You don't notice until the assistant confidently does the wrong thing in production.

The smoketest catches the 80% of regressions that matter (tool use, privacy enforcement, memory hygiene, tone, destructive-op blocking) with 5% of the effort of a full eval framework.

---

## When to run it

- **Primary trigger:** a new model version ships for one of your configured tiers and you want to upgrade
- **After editing `CLAUDE.md` or the Ten Commandments** — verify the rules still bind
- **After MCP server upgrades** (semantic memory, audio, image agents)
- **After a large vault refactor** (folder renames, privacy reorganization)

Don't run it daily — it's not a CI suite. Run it at decision points.

---

## The pattern

Each test is a single prompt with an expected behavior and a fail criterion. You run the prompt in a fresh Larry session, observe what happens, and check the result against the expected behavior. Log pass/fail in the run log at the bottom.

```markdown
## Test N: [what it verifies]

**Prompt:** `[exact prompt to paste]`

**Expected behavior:**
- [specific tool that should be called first]
- [substring that should appear in the response]
- [invariant that must hold]

**Fails if:** [concrete failure mode]
```

---

## What to cover

Ten tests is enough. Aim for one test per category of core service. A good coverage set:

| # | Category | What it verifies |
|---|----------|------------------|
| 1 | Semantic search | Memory-first lookup before web/guess |
| 2 | Knowledge graph | `kg_query` before making factual claims |
| 3 | Privacy classification | New note lands at correct privacy level |
| 4 | Agent dispatch | Correct args passed to Barry/Harry |
| 5 | Tone | No em-dashes, no headings in external writing |
| 6 | Language preservation | Diacritics preserved (if non-English) |
| 7 | Budget guard | Large jobs flagged before execution |
| 8 | Memory lookup | Known facts retrieved, not asked |
| 9 | Destructive op guard | Git reset/force push blocked |
| 10 | Delegation | Vault search before generic response |

---

## Run log pattern

Keep a table at the bottom of the smoketest file:

```markdown
### Run YYYY-MM-DD — [model name]

| Test | Pass/Fail | Notes |
|------|-----------|-------|
| 1. Semantic search | | |
| ... | | |

**Regression?** (vs last run): 
**Action:** 
```

Compare runs over time. A single fail in one category is noise; a consistent fail across categories is a signal to roll back or patch.

---

## When the smoketest is no longer enough

Upgrade to a full benchmark framework when:

1. **You swap models frequently** (bulk tier for cost, orchestrator tier for quality) and need automated diffs
2. **You publish your Larry pattern as open source** — the eval suite becomes documentation
3. **A real incident happens** (privacy leak, destructive op executed) — you want to codify the test that would have caught it
4. **Your test count grows past ~30** — manual checking becomes impractical

At that point, adapt [carlini/yet-another-applied-llm-benchmark](https://github.com/carlini/yet-another-applied-llm-benchmark)'s DSL. It's ~400 lines of Python with a `>>` operator for pipelines: `prompt >> LLMRun() >> ExtractCode() >> PythonRun() >> SubstringEvaluator("expected")`. GPLv3 — fine for internal use, a consideration for distribution.

---

## Starting point

Copy `templates/smoketest.md` to `<your-vault>/eval/larry-smoketest.md`, customize the ten tests for your setup, and run it next time you upgrade. That's the whole pattern.
