# Autonomous Loops

Self-prompting loops (the "Ralph Wiggum" pattern, also available as an official
Anthropic plugin) let Claude Code iterate on a task until a completion condition
is genuinely true: a stop hook intercepts session exit and re-feeds the same
prompt, with all file changes and git history preserved between iterations.

This document is the field-tested recipe for using loops safely in a vault
system. The pattern was validated here on a vault hygiene backlog: 52
frontmatter failures to zero in one iteration, including a corruption bug the
loop's own verification pressure surfaced.

## The three non-negotiables

A loop without these is an infinite loop with your token budget:

1. **A deterministic judge.** A script whose exit code defines done -- not a
   feeling, not "looks clean now". Example: `scripts/frontmatter_check.py`
   prints `FAILURES: N` and exits 0 only at zero. The loop prompt orders the
   model to run the judge every iteration and only claim completion when the
   judge says so.
2. **A completion promise** tied to the judge's output, e.g.
   `--completion-promise "THE CHECKER REPORTS ZERO FAILURES"`. The loop's rule
   ("never output a false promise to escape") is the quality mechanism: it
   forces re-verification, and re-verification finds real bugs.
3. **A max-iterations cap** as the backstop when the task turns out to be
   harder than the judge assumed.

## The loop prompt skeleton

```
Mission: drive <judge command> to zero failures.

PER ITERATION:
1. Run the judge.
2. If zero: verify once more, then output the promise phrase exactly.
3. Otherwise: fix up to N flagged items, re-run the judge, let the loop recycle.

FIX RULES:
- <your conventions: required fields, valid values, encoding>
- ROOT CAUSE: if a producer (script, prompt template) generates broken output,
  fix the producer too, so the failure class dies at the source.
- Commit per iteration with a descriptive message. Never commit private dirs.

Previous iterations are visible in git history and the judge's falling count.
```

## Practical gotchas (learned the hard way)

- The plugin's setup script does not survive multi-line prompts (bash eval
  errors). Start the loop with a one-line prompt, then edit
  `.claude/ralph-loop.local.md` and paste the full instruction into the body.
- The state file is not always cleaned up after a fulfilled promise. Check for
  a stale `.claude/ralph-loop.local.md` afterwards, or the next session may be
  re-prompted into the old loop.
- Pair the loop with a *fixer* the model can call (`scripts/frontmatter_fix.py`)
  so mechanical classes are handled in bulk and the model's judgment is spent
  on the genuinely ambiguous cases.
- Don't point loops at daemon infrastructure. Loops belong in the work layer
  (vault hygiene, migrations with green-tests exit conditions, refactors) --
  not in the nervous system that other agents depend on.

## Scheduling

Long loops are night work. Pair them with your nightly runner the same way
other batches run, and budget them on whatever credit pool your plan allocates
for programmatic/agentic use rather than your interactive quota.

## Good first candidates

- Hygiene backlogs with a countable failure list (frontmatter, broken links)
- Migrations with a test suite as the judge ("all green" = promise)
- Anything where you can write the judge in 50 lines -- if you cannot define
  the judge, the task is not loop-shaped yet.
