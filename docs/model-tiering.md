# Model Tiering

One config file decides which model every part of the system uses. Nothing
else hardcodes a model string.

## The problem it solves

A personal AI system accumulates model references fast: a daemon here, a
nightly batch there, a CLI wrapper, a bot config, a shell profile. When a new
model ships you either update all of them or you run a mix of generations
without noticing.

The second outcome is the common one. References drift apart, some paths keep
running a model you retired months ago, and you find out when output quality
changes for reasons you cannot trace.

## The pattern

A single JSON file is the only place a model name appears:

```json
{
  "default": "<model-id>",
  "default_effort": "high",
  "escalation": "<model-id>",
  "escalation_effort": "high",
  "voice_sensitive_effort": "medium",
  "cli_fallback": "<model-id>",
  "escalation_effort_levels": ["xhigh", "max"]
}
```

A thin module reads it and exposes intent-named functions. Call sites ask for
what they need, never for a specific model:

```python
resolve_for_effort("xhigh")              # which model for demanding work
effort_for_tier("xhigh")                 # which effort flag to pass
resolve_for_effort("high", voice_sensitive=True)   # unedited user-facing text
```

Load the file on every call rather than caching it at import. A daemon that
has run for a week should pick up a config change without a restart.

## Why intent, not model names

`resolve_for_effort("xhigh")` says "this task is demanding". It does not say
"use model X". That indirection is the whole point:

- Swapping models is a one-line config change, not a search across the repo.
- Two tiers can collapse onto the same model with different effort levels, and
  no call site needs to know.
- Tiers can split apart again later without touching call sites.

Keep the resolver functions even when both tiers return the same model. They
are the seam that lets the tiering change shape.

## Effort is a tier dimension, not just a model dimension

Newer model families expose an effort or reasoning-depth parameter. That means
a tier is a pair: which model, and how hard it works.

When a single model is strong enough to serve both tiers, effort becomes the
only difference between them. That is a legitimate configuration, not a
degenerate one.

Two rules worth encoding:

**Pin the effort per tier, not per request.** A task that triggers escalation
should not also dictate maximum effort. Trigger and depth are separate
decisions.

**Reserve the top level for humans.** If your automation never uses the
highest effort setting, that level stays available for interactive work
without competing for the same budget.

## Voice-sensitive output needs its own level

Any text the user reads unedited, a daily brief, a digest, a notification,
should get an explicit effort level rather than inheriting the default.

Higher effort produces longer and more exploratory text. For something meant
to be skimmed in thirty seconds that is the wrong direction. The goal for
those surfaces is that they sound right, not that they score maximally.

Give them their own config key so a change to the default tier does not
silently change how your daily brief reads.

## Know which resource is actually scarce

If your system calls the API directly, the scarce resource is money and you
should reason in cost per token.

If it runs through a subscription-based CLI, the scarce resource is usage
allowance. Those lead to different choices. Raising effort costs nothing extra
in dollars on a subscription but consumes allowance faster.

Check which one applies before optimizing. A system can be built entirely on
the subscription path and still contain a module that quietly opens an API
connection.

## Anti-pattern: deriving one role from another

If an advisor, judge or reviewer model is meant to be stronger than the
executor, do not derive it from the tiering config:

```python
executor = default_model()
advisor  = escalation_model()   # wrong
```

This works only while the tiers hold different models. The day they collapse
onto one, the model starts consulting itself, and nothing fails loudly. You
keep paying for a second opinion that cannot differ from the first.

Name the stronger role explicitly, and add a test asserting the two are
different.

## Testing

Test the resolver, not the model names, with two exceptions worth pinning:

- Voice-sensitive resolution differs from the default tier. If someone removes
  the config key, the test should fail rather than silently fall back.
- Escalation returns a model at least as capable as the default, if your
  system depends on that ordering.

## See also

- [token-hygiene.md](token-hygiene.md) for spend control
- [ARCHITECTURE.md](../ARCHITECTURE.md#model-configuration-per-mode) for
  per-modality model choices
