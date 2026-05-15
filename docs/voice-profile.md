# Voice Profile

A structured approach to capturing your voice, taste, and decision-making patterns so every agent in the ecosystem writes more like you. Not a personality description -- an operational specification that changes AI output.

## Architecture

Three layers work together:

```
Knowledge Graph (Milla)     -- queryable facts, surfaced on demand
  kg_query("voice rule")    -- returns relevant rules for current task

Eval Gate (deterministic)   -- catches violations post-output
  eval-rules.yaml           -- regex patterns for banned phrases/patterns

Inject Hook (contextual)    -- surfaces right rules at right moment
  inject-context.py         -- matches file path to voice hints on Edit/Write
```

### Why three layers

A single file of voice rules loaded every session gets ignored. 100 rules in context means 0 rules applied. The three-layer approach solves this:

- **Milla KG**: surgical retrieval. Query only what you need for the current task.
- **Eval gate**: deterministic catch. No LLM judgment required -- regex flags violations.
- **Inject hook**: contextual delivery. Writing an email? Get email rules. Writing lyrics? Get lyrics rules.

## Setup

### 1. Run the taste interview

Start a fresh Claude session. Use the interview prompt from the `templates/` directory (or write your own). Key areas to cover:

- **Writing mechanics**: How you build sentences, punctuation, paragraph structure
- **Aesthetic crimes**: What makes you physically cringe in others' writing
- **Beliefs and contrarian takes**: What you believe that others in your field don't
- **Communication registers**: How your voice changes by context (not by channel)
- **Decision rules**: How you judge quality, detect bullshit, build trust
- **Taste loves and disgusts**: Specific things you love/hate and why
- **Phrase bank**: Words you always use, words you never use
- **Productive contradictions**: Tensions that define you
- **Hard refusals**: Things you will never write, say, or fake

### 2. Load into Milla

Short facts go into the knowledge graph (128 char limit on object field):

```python
kg_add(subject="your_name", predicate="core_belief", object="Short belief statement")
kg_add(subject="your_voice", predicate="rule", object="Short voice rule")
kg_add(subject="your_voice", predicate="aesthetic_disgust", object="What you hate")
```

Rich content goes into drawers:

```python
add_drawer(wing="voice-profile", room="communication-registers", content="...")
add_drawer(wing="voice-profile", room="phrase-bank", content="...")
add_drawer(wing="voice-profile", room="aesthetic-crimes", content="...")
add_drawer(wing="voice-profile", room="decision-rules", content="...")
add_drawer(wing="voice-profile", room="taste-profile", content="...")
add_drawer(wing="voice-profile", room="contradictions", content="...")
add_drawer(wing="voice-profile", room="signature-tells", content="...")
```

### 3. Add eval-gate rules

Add patterns to `eval-rules.yaml` for your most common violations:

```yaml
- name: ai_generic_opening
  description: AI-generic opening phrases
  enabled: true
  severity: flag
  agents: ["larry-cli", "larry-bot"]
  conditions:
    - match_type: regex
      patterns: ["(?i)^(absolutely!|great question!|of course!)"]

- name: ai_therapy_speak
  description: Therapy language in output
  enabled: true
  severity: flag
  agents: ["larry-cli", "larry-bot"]
  conditions:
    - match_type: regex
      patterns: ["(?i)(i understand that it can feel|it's okay to|be kind to yourself)"]
```

### 4. Configure voice hints

Create `.claude/hooks/voice-profile-hints.json`:

```json
{
  "patterns": [
    {
      "match": ["email", "mail", "newsletter"],
      "context": "email",
      "hint": "VOICE/EMAIL: Your email-specific rules here."
    },
    {
      "match": ["linkedin", "social"],
      "context": "social",
      "hint": "VOICE/SOCIAL: Your social media rules here."
    }
  ],
  "default_hint": "VOICE: Your default voice rules here."
}
```

The `inject-context.py` hook reads `CLAUDE_TOOL` and `CLAUDE_TOOL_INPUT` environment variables. When the tool is Edit or Write, it extracts `file_path`, matches against patterns, and injects the hint via stderr.

## Usage at runtime

The agent doesn't need to think about this. The three layers work automatically:

1. Agent is about to write a file -> hook fires, injects relevant voice hint
2. Agent writes content with the hint in context
3. Eval gate checks output for violations, flags if needed
4. For deeper context, agent can query Milla: `kg_query("voice rule email")`

## Maintenance

Your voice changes. Update the profile when:

- You notice the agent drifting (add a new eval-gate rule)
- Your communication style shifts (update Milla drawers)
- You discover a new pattern worth preserving (add to KG)
- An old rule no longer applies (invalidate via `kg_invalidate`)

The nightly feedback audit (batch 7) can include voice-profile compliance in its Hot 10 report.
