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
│   ├── brains-bus-setup.md       <- SQLite event bus between agents, guarded by Parry
│   └── privacy-architecture.md   <- Privacy layers + auto-tagging + tone learning
├── templates/
│   ├── daily.md                  <- Daily note template
│   ├── project.md                <- Project template
│   ├── meeting.md                <- Meeting notes template
│   └── research.md               <- Research note template
├── scripts/
│   ├── load-context.sh               <- Session init hook (reads active context)
│   ├── collect-vault-data.sh         <- Nightly vault data collection
│   ├── harry_logger.py               <- Shared transcript-logger for Harry agents
│   ├── barry_audit.py                <- Unified JSONL audit-log for Barry events
│   ├── gws_mailer.py                 <- Outgoing-mail helper with local archiving
│   ├── parry-scheduled-task.xml      <- Windows Task Scheduler template for Parry autostart
│   └── register-parry-task.ps1       <- One-shot registration script (run once at setup)
├── .gitignore                    <- Template .gitignore for your vault
└── LICENSE
```

---

## The Four Agents

| Agent | Modality | What it does | Technology |
|-------|----------|-------------|------------|
| **Larry** | Text | Orchestrator. Thinks, writes, codes, plans, remembers. | Claude Code (Opus/Sonnet) |
| **Barry** | Image | Generates images, sorts visual material, maintains visual index. | Venice Chat via Playwright |
| **Harry** | Audio | Text-to-speech, music, sound effects, mixing. | Gemini TTS (Vertex AI) + FFmpeg |
| **Parry** | Filter | Privacy enforcement, tone control, quality gating. | Python middleware |

Larry orchestrates everything. Barry and Harry are invoked by Larry when needed. Parry runs as middleware on commits, sends, and generation.

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

---

## License

MIT. See [LICENSE](LICENSE).

This scaffold is provided as-is for personal use and adaptation. Do not include actual credentials or personal information when sharing your own fork.
