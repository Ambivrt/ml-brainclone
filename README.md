# ml-brainclone

A scaffold for building a personal AI second brain using **Claude Code** and **Obsidian**.

Larry is an AI-powered personal knowledge system that combines an Obsidian vault with Claude Code as the primary interface, plus specialized agents for image generation, audio/TTS, and privacy enforcement. Everything runs locally on your machine.

---

## What You Get

```
ml-brainclone/
├── README.md                     <- You are here
├── ARCHITECTURE.md               <- System design, tri-modal architecture, freedom router
├── SETUP.md                      <- Step-by-step installation guide
├── CLAUDE-template.md            <- Project instructions template (becomes CLAUDE.md)
├── docs/
│   ├── architecture-overview.md  <- Agent architecture + data flows
│   ├── larry-setup.md            <- Larry (Claude Code) configuration
│   ├── barry-setup.md            <- Barry (image agent) setup
│   ├── harry-setup.md            <- Harry (audio agent) setup
│   ├── mempalace-setup.md        <- MemPalace (semantic memory) setup + GPU config
│   ├── memory-system.md          <- Persistent memory architecture
│   ├── parry-setup.md            <- Parry (gatekeeper agent) setup + commands
│   ├── tarry-setup.md            <- Tarry (temporal agent) setup + queue + Task Scheduler
│   ├── farry-setup.md            <- Farry (translation skill) setup + Telegram commands
│   ├── brains-bus-setup.md       <- SQLite event bus between agents, guarded by Parry
│   ├── task-dispatch.md          <- Inter-agent work queue: dispatch from any channel
│   ├── proactivity.md            <- Larry acts, doesn't just report: scanner + dispatcher + nightly triggers
│   ├── privacy-architecture.md   <- Privacy layers + auto-tagging + tone learning
│   ├── eval-smoketest.md         <- Regression-check pattern for model swaps + CLAUDE.md edits
│   ├── skills-system.md          <- Skills: discovery, frontmatter format, self-patch
│   └── vault-ingest.md           <- Document conversion tool (MarkItDown)
├── templates/
│   ├── daily.md                  <- Daily note template
│   ├── project.md                <- Project template
│   ├── meeting.md                <- Meeting notes template
│   ├── research.md               <- Research note template
│   └── smoketest.md              <- 10-test regression smoketest (copy, customize, run)
├── scripts/
│   ├── load-context.sh               <- Session init hook (reads active context)
│   ├── collect-vault-data.sh         <- Nightly vault data collection
│   ├── proactive_scanner.py          <- Session-init scanner: auto-dispatch tasks for actionable state
│   ├── event_dispatcher.py           <- Bus-subscribing daemon: rules-based task generation
│   ├── harry_logger.py               <- Shared transcript-logger for Harry agents
│   ├── barry_audit.py                <- Unified JSONL audit-log for Barry events
│   ├── gws_mailer.py                 <- Outgoing-mail helper with local archiving
│   ├── vault-ingest.py               <- Convert documents (PDF/DOCX/PPTX/XLSX) to vault Markdown
│   ├── parry-scheduled-task.xml      <- Windows Task Scheduler template for Parry autostart
│   └── register-parry-task.ps1       <- One-shot registration script (run once at setup)
├── architecture/
│   ├── personalities/
│   │   ├── README.md                 <- Personality system: character sheets, switching rules, middleware
│   │   ├── _current-personality-template.md  <- Active personality tracker template
│   │   └── example-default/
│   │       └── character.md          <- Example default personality character sheet
│   └── telegram-v2-spec.md          <- Platform adapter spec: multi-channel message routing
├── .gitignore                    <- Template .gitignore for your vault
└── LICENSE
```

---

## The Agent Ecosystem

### Modalities (senses)

| Agent | Modality | What it does | Technology |
|-------|----------|-------------|------------|
| **Larry** | Text | Orchestrator. Thinks, writes, codes, plans, remembers. | Claude Code (Opus/Sonnet) |
| **Barry** | Image | Generates images, sorts visual material, maintains visual index. | Venice Chat via Playwright |
| **Harry** | Audio | Text-to-speech, music, sound effects, mixing. | Gemini TTS (Vertex AI) + FFmpeg |

### Services (organs)

| Agent | Function | What it does | Technology |
|-------|----------|-------------|------------|
| **Milla** | Memory | Semantic search, knowledge graph, diary, palace traversal. Never forgets. | MemPalace MCP (ChromaDB, GPU) |
| **Bert** | Emotion | Sentiment scoring, mood tracking, trend detection. Measures, never interprets. | XLM-RoBERTa (local GPU) |
| **Parry** | Judgment | Privacy enforcement, tone control, quality gating. | Python daemon (parry_service.py) |
| **Tarry** | Time | Reminders, follow-ups, recurring tasks, interrupted session recovery. | Python daemon (tarry_service.py) |
| **Carry** | Logistics | Transport content in/out/between systems. Pipelines with retry. | Python daemon (carry_service.py) |
| **Darry** | Sleep | Night shift 2.0: Light/Deep/REM sleep phases. Adaptive nightly processing. | Python daemon (darry_service.py) |
| **Scarry** | Conscience | Retroactive scanner. Finds procrastinated and forgotten tasks. Asks, never instructs. | Python script (scheduled) |
| **Farry** | Language | All languages, human and machine. Translation, explanation, code↔code. | Larry skill (inline) |

Larry orchestrates everything. Barry and Harry are invoked by Larry when needed. Daemons (Parry, Tarry, Carry, Darry) run in the background. Scarry runs on schedule via Darry. Farry and Bert are invoked on demand.

---

## Key Design Decisions

- **Text-only vault** — No binary files (images, audio) in the vault. External storage only. The vault is pure markdown.
- **Git sync** — The vault syncs via Git (private GitHub repo). No cloud drive dependencies.
- **Privacy layers** — Four levels (L1 public through L4 deeply personal), enforced by code.
- **Best model first** — Always use the best available model. Fall back to freer models only on guardrail refusal.
- **Robust over quick** — Never a hack. The system must be reliable enough to trust as your second brain.
- **Yolo mode** — Larry runs with `--dangerously-skip-permissions`. No confirmation prompts.
- **Nightly automation** — Scheduled tasks run overnight (Claude Haiku): vault hygiene, inbox triage, knowledge distillation.

---

## Prerequisites

| Component | Required? | Notes |
|-----------|-----------|-------|
| **Claude Code** | Yes | Claude Max subscription or API access |
| **Obsidian** (v1.12.4+) | Yes | Vault editor with CLI support |
| **Git** + GitHub | Yes | Vault sync (private repo recommended) |
| **Python 3.10+** | Yes | Agent scripts |
| **For MemPalace:** NVIDIA GPU (CUDA) | Recommended | Semantic memory layer (works on CPU too) |
| **For Barry:** Venice.ai account, Edge, Playwright | Optional | Image generation agent |
| **For Harry:** GCP + Vertex AI, FFmpeg | Optional | Audio/TTS agent |

---

## Quick Start

1. **Create your vault** and init a Git repo:
   ```bash
   mkdir ~/my-vault && cd ~/my-vault
   git init
   mkdir -p {00-inbox,01-personal,02-work,03-projects,04-knowledge,05-templates,06-archive,_private}
   ```

2. **Copy `CLAUDE-template.md`** into your vault root as `CLAUDE.md` and fill in the `{{PLACEHOLDER}}` values.

3. **Copy templates** from `templates/` into `05-templates/`.

4. **Copy scripts** from `scripts/` and configure the hook in `~/.claude/settings.json`.

5. **Start Larry**:
   ```bash
   cd ~/my-vault
   claude --dangerously-skip-permissions
   ```

See [SETUP.md](SETUP.md) for the full step-by-step guide.

---

## Placeholders

Throughout all files, replace these with your own values:

| Placeholder | Replace with |
|-------------|--------------|
| `{{USERNAME}}` | Your name or handle |
| `{{VAULT_PATH}}` | Path to your Obsidian vault |
| `{{ASSETS_PATH}}` | Path to your image/media assets |
| `{{AUDIO_PATH}}` | Path to your audio output |
| `{{GITHUB_REPO}}` | Your GitHub repo (e.g. `you/my-vault`) |
| `{{GCP_PROJECT}}` | Your Google Cloud project ID (for Harry TTS) |
| `{{NAS_PATH}}` | Your NAS/backup mount point |
| `{{VAULT_SLUG}}` | Claude Code project slug (e.g. `Users--you--vault`) |
| `{{PROJECT_NAME}}` | Your project/vault name |

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design philosophy, tri-modal architecture, freedom router, privacy model |
| [SETUP.md](SETUP.md) | Full installation walkthrough |
| [docs/architecture-overview.md](docs/architecture-overview.md) | Agent architecture, data flows, model routing |
| [docs/larry-setup.md](docs/larry-setup.md) | Larry (Claude Code) configuration details |
| [docs/barry-setup.md](docs/barry-setup.md) | Barry (image agent) pipeline |
| [docs/harry-setup.md](docs/harry-setup.md) | Harry (audio agent) pipeline |
| [docs/mempalace-setup.md](docs/mempalace-setup.md) | MemPalace semantic memory + GPU acceleration |
| [docs/memory-system.md](docs/memory-system.md) | How persistent memory works |
| [docs/privacy-architecture.md](docs/privacy-architecture.md) | Privacy layers and enforcement |
| [docs/logging-architecture.md](docs/logging-architecture.md) | Save-everything rule: transcript, audit, mail, event-bus |
| [docs/task-dispatch.md](docs/task-dispatch.md) | Inter-agent work queue: dispatch tasks from any channel (Telegram, mail, CLI) |
| [docs/proactivity.md](docs/proactivity.md) | Larry acts, doesn't just report: init-scanner + bus dispatcher + nightly triggers |
| [docs/agent-capabilities.md](docs/agent-capabilities.md) | Capability matrix for all agents: tools, skill domains, ecosystem flow |
| [docs/tarry-setup.md](docs/tarry-setup.md) | Tarry temporal daemon: reminders, follow-ups, Task Scheduler autostart |
| [docs/farry-setup.md](docs/farry-setup.md) | Farry translation skill: all languages, code↔code, Telegram /f command |
| [architecture/personalities/README.md](architecture/personalities/README.md) | Personality system: character sheets, switching rules, Parry middleware |
| [architecture/telegram-v2-spec.md](architecture/telegram-v2-spec.md) | Platform adapter spec: multi-channel message routing (Telegram, CLI, email) |

---

## License

MIT. See [LICENSE](LICENSE).

This scaffold is provided as-is for personal use and adaptation. Do not include actual credentials or personal information when sharing your own fork.
