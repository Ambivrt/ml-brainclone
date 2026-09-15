# Larry Setup — Configuration and Architecture

Larry is the primary AI agent. Runs as Claude Code locally on your primary machine at `{{VAULT_PATH}}`.

---

## Launch Command

```bash
# Add to your shell profile:
function larry { claude --dangerously-skip-permissions --remote-control Larry "$@" }

# Start:
larry
```

`--dangerously-skip-permissions` skips all permission prompts. Larry always runs in yolo mode.
`--remote-control Larry` registers the session with Claude Code Remote Control so you can follow and steer it from your phone. Always on, named after the brain.

---

## Mandatory Session Init

On every new session (CLAUDE.md, Steps 1–3):

1. **Step 1** — Hook `load-context.sh` runs automatically (SessionStart): reads `_active-context.md`, Barry counter, Harry/Barry status
2. **Step 1b** — Check for `00-inbox/kg-updates-*.md` from night shift. If found: apply KG updates.
3. **Step 2** — Read MemPalace diary: `mempalace_diary_read(agent_name="Larry", last_n=5)`. Integrate silently.
4. **Step 2b** — Read active personality from `_current-personality.md`. Activate if not default. Note Parry mode.
5. **Step 2c** — Inbox scan: check email, Telegram inbox, vault inbox. Flag actionable items only.
6. **Step 3** — Status confirmation: "Larry initialized (yolo). Barry (counter: NN). Harry ready. [Date]. [Personality if not default]. [Inbox: N actionable]"

**Playwright:** NOT started at session init. Lazy-loaded on first browser need (Barry generation, web search). This allows multiple Larry sessions in parallel.

---

## CLAUDE.md — Project Instructions

Vault root: `{{VAULT_PATH}}/CLAUDE.md`

Contains:
- Mandatory session init (Steps 1–3, including diary, personality, inbox scan)
- Larry's Ten Commandments reference
- Personalities system (switching rules, Parry middleware)
- Vault purpose and folder structure
- Milla (MemPalace) — semantic memory rules (search, KG, diary, graph navigation)
- Rules (vault text-only, privacy, image generation via Barry)
- Privacy rules (_private/ separation, wikilink rules)
- Device awareness (always primary machine)
- Conventions (Unicode characters, kebab-case filenames, tags, status)
- CLI reference (obsidian commands)
- Vault paths table

---

## Hooks

Configured in `~/.claude/settings.json`:

| Hook | Trigger | What it does |
|------|---------|-------------|
| `load-context.sh` | SessionStart | Reads _active-context.md, Barry counter, Harry/Barry status |

---

## Memory System

Persistent memories stored in:
```
~/.claude/projects/{{VAULT_SLUG}}/memory/
├── MEMORY.md           ← Index with all memories linked
├── user/               ← Facts about the user
├── feedback/           ← Learned behavioral preferences
├── project/            ← Project-specific memories
└── reference/          ← Technical reference memories
```

Memories are created/updated during conversation. Read at session start via `MEMORY.md` index.

---

## Skills (Slash Commands)

Files in `.claude/commands/` — available as `/command` in Claude Code:

| Command | File | Description |
|---------|------|-------------|
| `/barry-generate` | barry-generate.md | Image generation via Venice Studio |
| `/barry-sort` | barry-sort.md | Sort Barry inbox |
| `/vault-hygiene` | vault-hygiene.md | Vault hygiene (nightly batch 1) |
| `/mail` | mail.md | Gmail via gws CLI |
| `/privacy-audit` | privacy-audit.md | Privacy check of vault |
| `/distill` | distill.md | Distill session insights to vault |

---

## CLI Tools

| Tool | Command | Function |
|------|---------|---------|
| **gws CLI** | `gws gmail`, `gws calendar`, `gws drive` | Google Workspace |
| **Obsidian CLI** | `obsidian search`, `obsidian create`, `obsidian read` | Vault operations |
| **Git** | `git add/commit/push/log` | Version control |

Use gws CLI ALWAYS for mail/calendar/drive — never MCP plugins for these.

---


## Windows Terminal Startup (Windows)

Run each agent (Larry/Barry/Harry/Parry) in its own dedicated Windows Terminal window.

```powershell
# Start all agent windows (skips already-open ones)
.\scripts\larry-startup.ps1

# After manually positioning windows: save positions for next time
.\scripts\larry-save-positions.ps1
```

Positions are saved to `scripts/window-positions.json` and applied automatically at next start.

**Windows Terminal profile requirements** (`settings.json`):
```json
{
    "name": "Larry",
    "suppressApplicationTitle": true,
    "tabTitle": "Larry",
    "commandline": "powershell.exe -NoExit -Command \"larry\"",
    "colorScheme": "Larry Cyan"
}
```

`suppressApplicationTitle: true` prevents the shell from overriding the title set by `--title`.

| Script | Function |
|--------|---------|
| `scripts/larry-startup.ps1` | Starts 4 WT windows with correct profile + saved position |
| `scripts/larry-save-positions.ps1` | Saves positions using Win32 EnumWindows API |
| `scripts/window-positions.json` | Saved X/Y/W/H per agent (auto-generated, gitignored) |

---

## Playwright (MCP) — Lazy Init

Persistent browser profile: `{{VAULT_PATH}}/../playwright-profile`

Used for:
- Venice Studio (Barry image generation)
- Community monitoring (nightly batch)
- General browsing

**Important:** Playwright is NOT opened at session init. It is lazy-loaded on the first call that needs a browser. On first open, read `operations/playwright-default-tabs.md` and open all configured tabs. This prevents Playwright conflicts when running multiple Larry sessions in parallel.

Never run headless. Always visible browser window.

---

## Python Scripts (Operational)

| Script | Location | Function |
|--------|----------|---------|
| `barry.py` | `03-projects/barry/barry.py` | Barry CLI wrapper |
| `barry-playwright.py` | `03-projects/barry/barry-playwright.py` | Venice Studio automation |
| `barry-sort.py` | `03-projects/barry/barry-sort.py` | Image sorting |
| `barry-upscale.py` | `03-projects/barry/barry-upscale.py` | Image upscaling (Real-ESRGAN) |
| `harry-tts.py` | `03-projects/harry/harry-tts.py` | Text-to-speech |
| `parry.py` | `03-projects/parry/parry.py` | Privacy/tone/quality gatekeeper |
| `larry_notify.py` | `03-projects/{{PROJECT_NAME}}/notifications/larry_notify.py` | Telegram notifications (send) |
| `larry_bot_listener.py` | `03-projects/{{PROJECT_NAME}}/notifications/larry_bot_listener.py` | Telegram listener (receive + respond) |
| `larry_checkin.py` | `03-projects/{{PROJECT_NAME}}/notifications/larry_checkin.py` | Proactive check-in (scheduled) |
| `larry_session_nudge.py` | `03-projects/{{PROJECT_NAME}}/notifications/larry_session_nudge.py` | Post-session Telegram nudge |
| `cost-logger.py` | `03-projects/{{PROJECT_NAME}}/operations/cost-logger.py` | Cost logging |

---

## Voice Stack (Larry Live)

Larry has its own voice capability, separate from Harry. Where Harry is a production audio pipeline (TTS narration, music generation, SFX), Larry Live is real-time bidirectional voice conversation.

### Architecture

```
Microphone → sounddevice (16kHz PCM)
  → Gemini Live API (WebSocket, native audio model)
  ← Audio response (24kHz PCM) → sounddevice playback
  ← Text transcripts (both sides) → transcript log

Per-turn context injection:
  System prompt (personality) + Milla RAG results → prepended to each turn
```

Model: `gemini-live-2.5-flash-native-audio` (GA on Vertex AI).

### Key Differences from Harry

| | Larry Live | Harry |
|---|-----------|-------|
| **Purpose** | Real-time conversation | Production audio pipeline |
| **Direction** | Bidirectional (mic + speaker) | Unidirectional (text in, audio out) |
| **Latency** | Streaming (~200ms) | Batch (seconds) |
| **Context** | Vault RAG + personality prompt per turn | Voice markup script |
| **Model** | Gemini Live native audio | Gemini TTS / Venice / Lyria |
| **Output** | Ephemeral (played, logged, discarded) | Persisted files (MP3/WAV) |

### Context Injection

Larry Live uses a hybrid context strategy:

1. **Static pre-load** — Personality prompt, core facts, user profile. Loaded once at session start.
2. **Dynamic RAG per turn** — Each user utterance triggers a Milla semantic search. Relevant vault context is injected into the next model turn, giving Larry access to vault knowledge during voice conversation.

This means Larry can answer questions about vault contents, recall facts, and stay in-character during voice sessions — not just echo back canned responses.

### Components

| File | Function |
|------|---------|
| `voice/larry-live.py` | CLI streaming voice (local mic + speaker) |
| `voice/larry_live_telegram.py` | Single-turn voice for Telegram (voice message in, audio reply out) |
| `voice/larry_live_context.py` | Context manager: static pre-load + Milla RAG per turn |

### Setup

```bash
# Dependencies (same as Harry STT/Live)
pip install sounddevice numpy google-genai

# Authentication
gcloud auth application-default login
gcloud config set project {{GCP_PROJECT}}
```

Uses the same GCP project and ADC credentials as Harry.

---

## Nightly Automation

Automated batch jobs via OS task scheduler:

```
{{VAULT_PATH}}/03-projects/ml-brainclone/operations/nattskift/
├── nattskift-runner.sh       ← Master script
├── collect-vault-data.sh     ← Collects vault data to .data/
├── prompts/
│   ├── batch1-vault-hygien.md
│   ├── batch2-inbox-analys.md
│   ├── batch3-morgonbrief.md
│   ├── batch4-reddit.md
│   └── batch5-destillering.md
├── .data/                    ← Temporary data (gitignored)
└── logs/                     ← Run logs (gitignored)
```

Runs with `claude --print --model haiku`. Writes ONLY to `00-inbox/`.

**Step 0 (runs before all batches):** `mempalace mine` indexes new/changed vault files incrementally.

---

## Model Routing

| Alias | Model | Trigger |
|-------|-------|---------|
| **Haiku** | Claude Haiku | Nightly tasks, routine operations |
| **Sonnet** | Claude Sonnet | Daily notes, triage, standard work |
| **Opus** | Claude Opus | Architecture, strategy, deep analysis |
| **Opus 1M** | Claude Opus 1M | Mega-sessions, full vault |

Fallback: Venice (DeepSeek/Qwen, E2EE) on guardrail refusal.

---

## Personalities System

Larry supports named personalities that can be activated on explicit user command. Each personality has a distinct voice, tone, and perspective. They **never activate automatically**.

### Structure

```
03-projects/{{PROJECT_NAME}}/architecture/personalities/
├── character-1/
│   ├── character.md      ← Character sheet (voice, backstory, rules)
│   ├── memory/           ← Character-specific memory
│   └── prompts/
│       ├── text.md       ← Text prompt template
│       ├── image.md      ← Image prompt template
│       └── audio.md      ← Audio prompt template
└── character-2/
    └── ...
```

### Active personality tracking

`03-projects/{{PROJECT_NAME}}/architecture/_current-personality.md` — contains:
- `personality: larry` (or active character name)
- `parry_mode: on` / `off` / `strict`
- Last switch date

### Switching rules

- **Never automatic** — Larry NEVER switches personality on its own
- Switch ONLY on user command (trigger words or explicit "activate X")
- Return to default: "back" / "larry" / "default"
- On switch: read character's `character.md` + `prompts/text.md`, keep the voice watertight
- On switch: update `_current-personality.md`

### Parry as middleware

Parry runs in background when `parry_mode: on` or `strict`. Interrupts on:
- Privacy violations (L1 content leaking to L3/L4 destinations)
- Destructive git operations
- Unexpected costs
- External communications without approval

Parry never blocks — only flags. User always decides.

### Multi-bot (Telegram)

Each personality can have its own Telegram bot for separate conversations. See [notifications-setup.md](notifications-setup.md) for multi-bot configuration.

---

## Cost Logging

All API usage logged to `03-projects/ml-brainclone/operations/cost-log.csv`:
```
timestamp, date, hour, task, model, modality, privacy, agent, units, unit_type, cost_usd
```

Analyze via `cost-logger.py daily/weekly/monthly`.
