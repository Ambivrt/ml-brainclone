# System One in Practice — from shadow to live

`docs/decision-gate.md` describes the mechanism: a small model that answers typed questions (yes/no probability, choice, score) with calibrated probabilities and a separate confidence, and code that weighs them against named thresholds. This document is what came after the gate: the rules that made it safe to use in more places, the path from shadow to live, and where it paid off.

The implementation here uses [Jev from TypeSafe](https://typesafe.ai/blog/introducing-system-one-models-and-jev): sub-second calls at a fraction of a cent per thousand. Any model that answers typed questions with calibrated probabilities fits the pattern.

---

## Rules for asking

- **Atomic questions.** One gut feeling per question. The weights live in your code, not in the prompt.
- **Always a way without it.** Every caller has a path that works when the service is down or blocked. The model is optional, never a requirement.
- **`escalate` and fit.** Every `choice` gets an `escalate` option and a fit-`noul` per candidate. A choice is accepted only above a confidence and a fit threshold; otherwise the old logic decides, and the reason (`escalated`, `low_confidence`, `low_fit`, `invalid_response`) is logged.
- **Hard limits before every call:** a privacy ceiling per purpose (L2 by default, L3 only where decided, L4 never), a secrets filter, a monthly budget, and a mandatory `purpose` so every cent traces back to its caller. The state itself is never logged.

---

## Shadow, hybrid, live

Nothing goes straight into control.

1. **Shadow.** The model judges *beside* the existing logic and writes its verdict to a shadow file. Nothing reaches the owner, nothing changes behaviour. A cache on content hash makes reruns free; the first service error stops the rest of the run.
2. **Decision trail.** One line per decision: hashes, the model's choice, what the old logic chose, the fallback reason, confidence, fit. Never content. Optionally the full input (up to L3) for replay.
3. **Verdicts.** A replay tool lets the owner judge disagreements one by one. Thresholds are calibrated against judged cases, not by feel.
4. **Hybrid.** The model decides where it has proven itself, the old logic everywhere else. A flag per use, not per system.
5. **Live.** Only after the owner has seen the shadow and said yes.

Good first uses, measured here: routing an incoming chat message to the right agent, picking reminders out of free text (it caught every one a regex missed), extracting fields from mail, recalling the right memory among hundreds while loading 3 % of the index, deciding the effort level and tool profile of a task before it starts.

---

## Foreman shadow — judging the night shift

An application of the same pattern to long-running batches, after [foreman](https://github.com/thruwire/foreman). After the night shift, a step reads each batch transcript afterwards and has the model score a set of signals per checkpoint: stuck, off track, done, requirements met, needs verification, needs a human. A pure arbiter maps the scores to `CONTINUE / STEER / STOP / RETRY / START_VERIFIER / FINISH / ESCALATE`.

It steers nothing. It sends no tool results, redacts private paths, and skips batches that touched L3. It runs last in the runner with a hard timeout and `|| true` (`run_shadow` in `scripts/nightly-runner.sh`).

What the first week showed: "stuck" and "off track" never fired on real nights, and the model rated successful batches well below foreman's default "done" threshold. Calibrate against judged cases before any of it steers.

---

## See also

- `docs/model-tiering.md` — which model does what
- `docs/privacy-architecture.md` — levels
- `scripts/nightly-runner.sh` — `run_shadow`
