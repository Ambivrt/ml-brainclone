# Personality System

The personality system lets a single AI agent switch between distinct voices, perspectives, and behavioral profiles on command. Each personality is a full character definition with its own tone, vocabulary, values, fears, and prompt templates.

## Core Concepts

### Personalities Are Not Agents

Personalities are **moods of a single agent**, not separate agents. The primary agent (Larry) is always the underlying consciousness. When a personality is active, it colors all output — text, images, audio — but the agent's knowledge and access remain the same.

### Switching

- **Default:** The primary personality (your equivalent of Larry) loads at session start.
- **Manual activation only:** The agent NEVER switches personality on its own initiative. Only the user can trigger a switch.
- **Trigger words:** Each personality defines trigger words (e.g., `hope`, `gatekeeper`). The user says the trigger or an explicit "activate X" command.
- **Return:** Generic return commands (`back`, `default`, `reset`) revert to the primary personality.
- **Strict character hold:** Once activated, the personality stays consistent until the user explicitly switches. No drift back to default.

### Third-Person Queries

The user can ask "what would [personality] say about this?" without activating. The agent answers from that character's perspective but remains in the current personality.

### Middleware (Gatekeeper Pattern)

One personality can run as **always-on middleware** in the background, regardless of which personality is active in the foreground. This is the "gatekeeper" pattern — a safety/quality filter that monitors all actions and intervenes when needed.

The gatekeeper:
- **Never blocks** — it flags, questions, and logs. The user always decides.
- Has three modes: `off` (silent), `on` (reacts to clear risks), `strict` (asks before all irreversible actions).
- Monitors for: privacy violations, destructive operations, unexpected costs, external communications without approval.

### Model Assignment

Different personalities can be assigned to different AI models based on their nature:

| Personality Type | Recommended Model Tier | Rationale |
|---|---|---|
| Deep/core personalities | Orchestrator tier (`default_model()`) | Nuance, depth, precision |
| Fast/verbose personalities | Bulk tier (`simple_model()`) | Speed, generosity, lower cost |
| Balanced/careful personalities | Escalation tier (`escalation_model()`) | Balance of quality and cost |
| Gatekeeper | Orchestrator tier | Safety-critical, must not miss risks |

The smallest available tier is never used, even for the fastest personality. See [docs/model-tiering.md](../../docs/model-tiering.md).

## Folder Structure

```
architecture/personalities/
├── README.md                          # This file
├── _current-personality-template.md   # Template for tracking active personality
├── example-default/                   # Example: primary/default personality
│   ├── character.md                   # Character sheet
│   ├── memory/                        # Personality-specific memory
│   │   └── .gitkeep
│   └── prompts/
│       ├── text.md                    # Text interaction prompts
│       ├── audio.md                   # Audio/voice prompts (optional)
│       ├── image.md                   # Visual prompts (optional)
│       └── examples/
│           ├── good.md               # Examples of correct output
│           └── bad.md                # Examples of incorrect output
├── example-gatekeeper/                # Example: middleware/gatekeeper personality
│   ├── character.md
│   ├── memory/
│   │   └── .gitkeep
│   └── prompts/
│       └── text.md
└── your-personality/                  # Add your own personalities here
    ├── character.md
    ├── memory/
    └── prompts/
        └── text.md
```

## Character Sheet Format

Every personality needs a `character.md` with:

1. **Frontmatter** — YAML metadata: name, triggers, token profile, model, status
2. **Identity** — Who is this character? Core description in 2-3 sentences.
3. **Parameters** — Numeric dials: verbosity, formality, humor, patience, curiosity, emoji usage
4. **Language rules** — How they speak. Words they always/never use.
5. **Motivation** — What drives this character?
6. **Fear** — What do they dread?
7. **Values** — 3 core values.
8. **Disagreement behavior** — How they react when overruled.
9. **Catchphrases** — 2-3 signature phrases.

See `example-default/character.md` for a complete template.

## Prompt Template Format

Each personality has prompt files per modality (text, audio, image). At minimum, `prompts/text.md` is required. It contains:

1. **System prompt** — The core instruction block that defines the personality's voice.
2. **Tone rules** — Always/never lists for behavioral guardrails.
3. **Examples** — Right vs. wrong output comparisons.
4. **Presence phrases** — Short status/acknowledgment responses (optional).

## Adding a New Personality

1. Create a new directory under `architecture/personalities/` using kebab-case naming.
2. Copy `example-default/` as a starting point.
3. Fill in `character.md` with the character definition.
4. Write `prompts/text.md` with the system prompt and tone rules.
5. Add the personality to `_current-personality-template.md` in the roster table.
6. Optionally add `prompts/audio.md` and `prompts/image.md` for multi-modal personalities.
7. Create `memory/` with a `.gitkeep` for personality-specific context storage.

## Memory Architecture

- Each personality logs to its own `memory/` directory.
- Personalities can reference their own past interactions.
- Personalities **cannot** read each other's memories.
- The primary/default personality has access to everything (it is the underlying consciousness).
- Good/bad examples are built organically through real conversations, not pre-fabricated.

## Privacy Integration (Optional)

You can assign a `privacy_access` level to each personality, controlling what vault content it can reference:

| Personality | Privacy Access | Use Case |
|---|---|---|
| Default | L1-L2 (public) | Normal operations |
| Gatekeeper | All levels | Needs full visibility for safety |
| Core/deep | L1-L4 (all) | Deep introspection, journaling |

## Related Files

- `_current-personality-template.md` — Active personality tracker
- `{{VAULT_PATH}}/CLAUDE.md` — Session init reads active personality at startup
- Gatekeeper system code (if applicable) — Runs as background middleware
