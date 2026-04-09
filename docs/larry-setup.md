# Larry Setup — Configuration and Architecture

Larry is the primary AI agent. Runs as Claude Code locally on your primary machine at `{{VAULT_PATH}}`.

---

## Launch Command

```bash
# Add to your shell profile:
function larry { claude --dangerously-skip-permissions "$@" }

# Start:
larry
```

`--dangerously-skip-permissions` skips all permission prompts. Larry always runs in yolo mode.

---

## Mandatory Session Init

On every new session (CLAUDE.md, Steps 1–3):

1. Hook `load-context.sh` runs automatically (SessionStart)
2. Larry reads `_active-context.md` — ongoing work, blockers, status
3. Larry reads `{{ASSETS_PATH}}/.counter` — Barry's image counter
4. Larry reads `03-projects/harry/harry.md` and `03-projects/barry/barry.md`
5. Larry opens default Playwright tabs (see `operations/playwright-default-tabs.md`)
6. Status confirmation: "Larry initialized (yolo). Barry (counter: NN). Harry ready. Playwright: N tabs. [Date]."

---

## CLAUDE.md — Project Instructions

Vault root: `{{VAULT_PATH}}/CLAUDE.md`

Contains:
- Mandatory session init (Steps 1–3)
- Vault purpose and folder structure
- Rules (vault text-only, privacy, etc.)
- Device awareness (always primary machine)
- Conventions (filenames, tags, status)
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

## Playwright (MCP)

Persistent browser profile: `{{VAULT_PATH}}/../playwright-profile`

Used for:
- Venice Studio (Barry image generation)
- Community monitoring (nightly batch 4)
- General browsing

Default tabs opened at session start (see `operations/playwright-default-tabs.md`).

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
| `cost-logger.py` | `03-projects/ml-brainclone/operations/cost-logger.py` | Cost logging |

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

## Personalities (Optional System)

Larry supports named personalities that can be activated on explicit command. Each personality has a distinct voice, tone, and perspective. They never activate automatically.

Implement by creating character sheets in `03-projects/ml-brainclone/personalities/`:
```
personalities/
├── character-1/
│   ├── character.md      ← Character sheet
│   ├── memory/           ← Character-specific memory
│   └── prompts/
│       ├── text.md       ← Text prompt template
│       ├── image.md      ← Image prompt template
│       └── audio.md      ← Audio prompt template
└── character-2/
    └── ...
```

Current personality tracked in `_current-personality.md`.

---

## Cost Logging

All API usage logged to `03-projects/ml-brainclone/operations/cost-log.csv`:
```
timestamp, date, hour, task, model, modality, privacy, agent, units, unit_type, cost_usd
```

Analyze via `cost-logger.py daily/weekly/monthly`.
