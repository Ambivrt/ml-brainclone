# Typed Decision Gate: A System One Decision Model in Front of Text

A small external decision model that writes no text at all, only typed answers to typed questions, sitting in front of anything that wants to interrupt you.

## The problem it solves

Most of what a personal agent system needs to decide is not "write me a paragraph", it is "yes or no", "which of these three categories", or "how urgent is this on a four-point scale". Answering those questions with a full conversational model is expensive relative to the value returned, and it produces free text you then have to parse back into a decision anyway.

The harder problem is judgment quality on the gating question itself. A system that decides on its own what's worth interrupting you for tends toward one of two failure modes: it interrupts too much and gets ignored, or it goes quiet to avoid interrupting and then misses things that actually mattered. Neither failure is solved by writing better prompts. It needs a model whose whole job is producing calibrated probabilities on a fixed small set of questions, and code that weighs those probabilities against named thresholds rather than trusting the model to make the call.

## The mechanism

The reference system nicknames this component Jev. Three things make the pattern more than "call a classifier":

**Typed input and output, not text.** The caller passes a text description of the state and a set of typed questions: a yes/no probability question, a choice among a fixed set of labeled options, or an ordered score. The model comes back with probabilities and a confidence value for each, never prose.

```python
def yes_no(instructions: str) -> dict:
    """Yes/no question. Answer is the probability of yes, 0 to 1."""
    return {"type": "yes_no", "instructions": instructions}

def choice(instructions: str, criteria: dict[str, str]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}

def score(instructions: str, criteria: list[str]) -> dict:
    """Rate against ordered levels, lowest first."""
    return {"type": "score", "instructions": instructions, "criteria": criteria}

result = decision_model.ask(
    state=text,
    privacy=2,
    purpose="triage-inbound",
    questions={
        "needs_action": yes_no("The message requires the recipient to do something"),
        "urgency": score("How soon does this need attention", [
            "no time pressure", "within weeks", "this week", "harms them if not now",
        ]),
    },
)
if result.answers["needs_action"]["p_yes"] > 0.8:
    ...
```

**Guards in code before every call, not in the prompt.** Because this model runs outside your own infrastructure, every call passes through a fixed sequence of checks that live in code, not in instructions to the model:

- a privacy ceiling per purpose (what's allowed to leave the machine at all, deny by default for anything unrecognized)
- a secret-pattern scan, the same one used before any external model call
- a hard monthly budget cap, single-digit dollars in the reference system, enforced before the call is made rather than noticed afterward
- a cost ledger that logs tokens, cost, and purpose in an append-only file, but never the content of the state or the question

```python
def ask(state, questions, *, privacy, purpose, ...):
    if privacy > privacy_cap(purpose):
        raise Blocked(f"privacy L{privacy} exceeds cap for {purpose!r}")
    if secret_hits(state, questions):
        raise Blocked("secret pattern matched, call refused")
    if month_to_date_cost() >= monthly_budget():
        raise Blocked("monthly budget exhausted")
    # only now does a network call happen
```

**The model proposes, code decides.** The gate never lets a probability alone trigger an action. Named thresholds in code weigh the answers, and any answer that would suppress something (drop it silently) additionally requires a code-side signal, not just a model judgment, before it's allowed to do that.

```python
T_NEEDS_DECISION = 0.7
T_SELF_INFLICTED = 0.5

def decide(item, answers):
    self_inflicted = answers["self_inflicted"]["p_yes"]
    needs_decision = answers["needs_action"]["p_yes"]
    wants_drop = self_inflicted >= T_SELF_INFLICTED or needs_decision < T_NEEDS_DECISION
    if wants_drop and not item.code_confirms_self_inflicted:
        # A model's read of the text can downgrade urgency, never silence it outright.
        return "hold", "downgraded to hold, no code signal confirms the drop"
    if wants_drop:
        return "drop", "confirmed self-inflicted, resolved quietly"
    return "pass", "surfaced to the human"
```

That last rule matters more than it looks. The state text fed to the model can include raw content from outside the system (an inbound message, a scanned thread). If a clever phrasing in that text alone could talk the gate into dropping something, an untrusted sender could suppress their own message from ever reaching you. Requiring an independent, code-set signal before an item can be dropped closes that path.

## Running it in shadow mode first

Before trusting a new gate to actually suppress or route anything, run it in shadow mode: it judges every item, records the verdict and the reasoning to a daily audit file, but a separate flag controls whether anything downstream actually acts on the verdict. With the flag off, existing behavior is unchanged and you get a full trail of what the gate would have decided, which you can review before turning it on for real.

```python
SHARP = False  # flip this only after reviewing shadow output

def shadow_hook(source, text, privacy, ...):
    verdict = judge(item, ...)
    append_to_shadow_log(item, verdict)
    if SHARP:
        return verdict
    return None  # existing code path runs exactly as it did before
```

A daily report over the shadow log, grouped by source and by verdict, with the most uncertain calls (closest to a threshold) listed separately, is the fastest way to tell whether the thresholds are calibrated before flipping the switch.

## How to adopt this in a fork

1. Before adopting an external decision model at all, check whether a local classifier or a handful of regex rules solves your actual problem. The typed-gate pattern earns its complexity only once you have several different callers that all need the same kind of judgment call and you want one place to tune it.
2. Define the fixed set of question types you need (yes/no, choice, ordered score is usually enough) and write the wrapper that validates a question dict against that shape before it's sent anywhere.
3. Build the guard chain first: privacy cap, secret scan, budget cap, cost ledger. None of them depend on the decision model existing yet, and they're the part that actually protects you.
4. Add the code-side decision function with named threshold constants. Resist the urge to let the model's own confidence output double as the threshold; pick numbers, write down why, and put them in one place.
5. Run everything in shadow mode against real traffic for a week or two before it's allowed to suppress or route anything for real.
6. Keep the audit log even after going live. The moment you stop being able to see why something was dropped is the moment you stop trusting the gate.

## Pitfalls

**Unknown privacy level treated as low-sensitivity.** Default an unrecognized privacy level to the most cautious interpretation, not the least. A source that forgot to tag its own sensitivity should never get treated as safe by omission.

**Letting the model's text decide whether to trust the model's text.** If the state being classified came from outside your system (an inbound message, a scraped page), don't let anything within that text single-handedly authorize a suppression. The self-inflicted-error check in the mechanism above exists specifically to keep an external sender from talking their way out of surfacing to you.

**A network call on the same thread as something time-sensitive.** A decision-model call is a network round trip. Anything gating a real-time path needs a hard wall-clock timeout and a graceful "unjudged" fallback that lets the default (pre-gate) behavior proceed, rather than blocking on a slow or down external service.

**Treating "unjudged" as "drop".** When the gate can't reach a verdict (timeout, budget exhausted, privacy cap exceeded), that is not the same as a negative verdict. Unjudged items should fall through to whatever behavior existed before the gate was added, not be silently discarded.

## See also

- [oversight.md](oversight.md) for the layer that governs what happens once something is judged worth surfacing to you
- [model-tiering.md](model-tiering.md) for a related pattern of routing by intent rather than hardcoding a specific model
