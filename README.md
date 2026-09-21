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
├── docs/                          <- incl. model-tiering.md, output-lifecycle.md
│   ├── blueprint.md              <- Generated: directories, daemons, entrypoints, deps of a working install
│   ├── architecture-overview.md  <- Agent architecture + data flows
│   ├── larry-setup.md            <- Larry (Claude Code) configuration
│   ├── barry-setup.md            <- Barry (image agent) setup
│   ├── harry-setup.md            <- Harry (audio agent) setup
│   ├── garry-setup.md            <- Garry (spatial agent) setup + Trellis 2 + Blender
│   ├── mempalace-setup.md        <- MemPalace (semantic memory) setup + GPU config
│   ├── memory-system.md          <- Persistent memory architecture
│   ├── parry-setup.md            <- Parry (gatekeeper agent) setup + commands
│   ├── tarry-setup.md            <- Tarry (temporal agent) setup + queue + Task Scheduler
│   ├── karry-setup.md            <- Karry (location agent), discontinued, pattern reference only
│   ├── farry-setup.md            <- Farry (interpreter service) setup: live translation, format conversion
│   ├── model-tiering.md          <- One JSON tier file, orchestrator/bulk/on-request models, effort levels
│   ├── oversight.md              <- Human-in-the-loop: in_loop/on_loop/autonomous, the ask module
│   ├── status-file.md            <- Code-generated status file that replaced daily notes
│   ├── decision-gate.md          <- Typed decision model outside the text gateway, shadow mode
│   ├── finish-the-job.md         <- Open-thread pickup, job receipts, capability suggestions
│   ├── code-layout.md            <- Source repo, deployed runtime, binaries, config: four separate places
│   ├── brains-bus-setup.md       <- SQLite event bus between agents, guarded by Parry
│   ├── task-dispatch.md          <- Inter-agent work queue: dispatch from any channel
│   ├── proactivity.md            <- Larry acts, doesn't just report: scanner + dispatcher + nightly triggers
│   ├── privacy-architecture.md   <- Privacy layers + auto-tagging + tone learning
│   ├── eval-smoketest.md         <- Regression-check pattern for model swaps + CLAUDE.md edits
│   ├── skills-system.md          <- Skills: discovery, frontmatter format, self-patch
│   ├── system-taxonomy.md        <- system/* tag schema + SYSTEM-INDEX pattern (separate system from personal)
│   ├── vault-hygiene.md          <- One filename one file, inbox never archived, the sync trap
│   ├── content-campaigns.md      <- Content campaign management: calendar + Tarry chains + morning brief
│   ├── autonomous-loops.md       <- Self-prompting loops: deterministic judge + completion promise
│   ├── multi-llm-gateway.md      <- Several model families behind one gate: secret scan, privacy policy, schema validation, cross-vendor review
│   └── vault-ingest.md           <- Document conversion tool (MarkItDown)
├── templates/
│   ├── daily.md                  <- Daily note template
│   ├── project.md                <- Project template
│   ├── meeting.md                <- Meeting notes template
│   ├── research.md               <- Research note template
│   ├── smoketest.md              <- 10-test regression smoketest (copy, customize, run)
│   └── system-index.md           <- SYSTEM-INDEX template with Dataview live-catalog
├── scripts/
│   ├── load-context.sh               <- Session init hook (reads active context)
│   ├── collect-vault-data.sh         <- Nightly vault data collection
│   ├── proactive_scanner.py          <- Session-init scanner: auto-dispatch tasks for actionable state
│   ├── event_dispatcher.py           <- Bus-subscribing daemon: rules-based task generation
│   ├── harry_logger.py               <- Shared transcript-logger for Harry agents
│   ├── barry_audit.py                <- Unified JSONL audit-log for Barry events
│   ├── gws_mailer.py                 <- Outgoing-mail helper with local archiving
│   ├── vault-ingest.py               <- Convert documents (PDF/DOCX/PPTX/XLSX) to vault Markdown
│   ├── nightly-runner.sh             <- Nightly batch runner (PATH hardening, singleton kill, batch dispatch)
│   ├── brief_output.py               <- Validated atomic write for the morning brief, see docs/security-untrusted-input.md
│   ├── collect-calendar.py           <- Deterministic calendar fetch (no LLM in the loop) for the morning brief
│   ├── prompts/batch3-morning-brief.md <- Example morning brief prompt with the untrusted-data section
│   ├── system_tag_batch.py           <- Path-based system/* tagging (idempotent), see docs/system-taxonomy.md
│   ├── inbox_reaper.py               <- Deletes expired auto-reports from 00-inbox, see docs/vault-hygiene.md
│   ├── parry-scheduled-task.xml      <- Windows Task Scheduler template for Parry autostart
│   └── register-parry-task.ps1       <- One-shot registration script (run once at setup)
├── tests/
│   ├── test_brief_output.py          <- brief_output.py: validation + atomic write + CLI mode
│   └── test_nightly_runner_readonly.py <- Structural checks on the morning brief's read-only hardening
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

12 agents: one orchestrator, three modalities, eight services. 10 daemons run under one watchdog with singleton locks and a circuit breaker (three failed restarts and it stops trying).

### Modalities (senses)

| Agent | Modality | What it does | Technology |
|-------|----------|-------------|------------|
| **Larry** | Text | Orchestrator. Thinks, writes, codes, plans, remembers. | Claude Code (see [docs/model-tiering.md](docs/model-tiering.md)) |
| **Barry** | Image | Generates images, sorts visual material, maintains visual index. | Venice Chat via Playwright |
| **Harry** | Audio | TTS, STT, realtime voice, music. Also runs a dictation daemon. | Gemini TTS (Vertex AI) + FFmpeg |
| **Garry** | Spatial | Image-to-3D mesh, background removal, Blender import, export into a game engine. | Trellis 2 + rembg + Blender |

### Services (organs)

| Agent | Function | What it does | Technology |
|-------|----------|-------------|------------|
| **Milla** | Memory | Semantic search, knowledge graph, diary, palace traversal. Never forgets. | MemPalace MCP (ChromaDB, GPU) |
| **Parry** | Judgment | Privacy enforcement, tone control, quality gating on the bus. | Python daemon (parry_service.py) |
| **Tarry** | Time | Reminders, follow-ups, recurring tasks, interrupted session recovery. | Brain runtime (tarry_brain.py, composes capabilities) |
| **Carry** | Logistics | Transport content in/out/between systems. Pipelines with retry. | Brain runtime (carry_brain.py, composes capabilities) |
| **Darry** | Sleep | Night shift: nine batches, morning brief at 05:30. Adaptive nightly processing. | Brain runtime (darry_brain.py, composes capabilities) |
| **Scarry** | Conscience | Retroactive scanner. Finds procrastinated and forgotten tasks, now also picks up open threads. | Python script (scheduled) |
| **Warry** | Emotion | Sentiment scoring, mood tracking, trend detection. Measures, never interprets. Local GPU. | Brain runtime (warry_brain.py) |
| **Farry** | Interpreter | Live translation ("Babel fish" mode), machine translation, format conversion (json/yaml/toml/xml/csv). Checks memory first for consistent terminology. | Translation/format service |

There is no video agent. Karry (a former location agent) is discontinued; see [docs/karry-setup.md](docs/karry-setup.md) for the pattern it left behind.

Larry orchestrates everything. Barry, Harry, and Garry are invoked by Larry when needed. Daemons run in the background. Each background agent runs as a Brain (a `*_brain.py` entrypoint that composes shared capabilities), brought up by a consolidated start script and kept alive by a heartbeat-aware watchdog. See ARCHITECTURE.md (Capability Composition). Parry stays a plain daemon (the bus gatekeeper). Scarry runs on schedule via Darry. Warry and Farry are invoked on demand.

---

## Key Design Decisions

- **Text-only vault**, No binary files (images, audio) in the vault. External storage only. The vault is pure markdown.
- **Git sync**, The vault syncs via Git (private GitHub repo). No cloud drive dependencies.
- **Privacy layers**, Four levels (L1 public through L4 deeply personal), enforced by code.
- **Best model first**, Always use the best available model. Fall back to freer models only on guardrail refusal.
- **Robust over quick**, Never a hack. The system must be reliable enough to trust as your second brain.
- **Yolo mode**, Larry runs with `--dangerously-skip-permissions`. No confirmation prompts, but this sits underneath an oversight layer, not instead of one: a rule engine decides per action whether it waits for a yes, happens with an undo window, or just gets logged. See [docs/oversight.md](docs/oversight.md).
- **Remote Control always on**, every session starts with `--remote-control <brain>` so it can be followed and steered from a phone.
- **Nightly automation**, nine scheduled batches run overnight, morning brief at 05:30. Bulk work (vault hygiene, inbox triage, knowledge distillation) runs on the cheapest model tier that clears the bar, never the smallest one. See [docs/model-tiering.md](docs/model-tiering.md).

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
| **For Garry:** Trellis 2, rembg, Blender 4.0+ | Optional | Spatial/3D agent |

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
   claude --dangerously-skip-permissions --remote-control Larry
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
| [docs/garry-setup.md](docs/garry-setup.md) | Garry (spatial agent) setup: Trellis 2, rembg, Blender |
| [docs/mempalace-setup.md](docs/mempalace-setup.md) | MemPalace semantic memory + GPU acceleration |
| [docs/memory-system.md](docs/memory-system.md) | How persistent memory works |
| [docs/privacy-architecture.md](docs/privacy-architecture.md) | Privacy layers and enforcement, including the read side: which folders a generator may scan |
| [docs/vault-hygiene.md](docs/vault-hygiene.md) | Filename collisions, inbox lifecycle, sync traps, gitignore pitfalls |
| [docs/logging-architecture.md](docs/logging-architecture.md) | Save-everything rule: transcript, audit, mail, event-bus |
| [docs/daemon-stability.md](docs/daemon-stability.md) | Daemon stability patterns: start scripts, heartbeats that prove responsiveness, client-side timeouts, circuit breakers, singleton guards, resource locking, PATH hardening |
| [docs/task-dispatch.md](docs/task-dispatch.md) | Inter-agent work queue: dispatch tasks from any channel (Telegram, mail, CLI) |
| [docs/proactivity.md](docs/proactivity.md) | Larry acts, doesn't just report: init-scanner + bus dispatcher + nightly triggers |
| [docs/agent-capabilities.md](docs/agent-capabilities.md) | Capability matrix for all agents: tools, skill domains, ecosystem flow |
| [docs/tarry-setup.md](docs/tarry-setup.md) | Tarry temporal daemon: reminders, follow-ups, release chains, Task Scheduler autostart |
| [docs/content-campaigns.md](docs/content-campaigns.md) | Content campaign management: calendar + Tarry chains + morning brief pipeline |
| [docs/karry-setup.md](docs/karry-setup.md) | Karry location agent (discontinued): kept for the hybrid daemon + MCP pattern |
| [docs/farry-setup.md](docs/farry-setup.md) | Farry interpreter service: live translation, format conversion |
| [docs/model-tiering.md](docs/model-tiering.md) | One config file decides every model choice: intent-named resolvers, effort as a tier dimension, voice-sensitive levels |
| [docs/output-lifecycle.md](docs/output-lifecycle.md) | Generated reports need an expiry, quality gates need to cover the surfaces you actually read |
| [docs/security-untrusted-input.md](docs/security-untrusted-input.md) | Prompt injection via scraped feeds, mail and calendar invites: read-only sessions, deterministic collectors, schema-validated writes |
| [docs/oversight.md](docs/oversight.md) | Human-in-the-loop rule engine: in_loop, on_loop, autonomous, the ask module |
| [docs/status-file.md](docs/status-file.md) | Code-generated status file that replaced daily notes |
| [docs/decision-gate.md](docs/decision-gate.md) | Typed decision model outside the text gateway: guards, shadow mode |
| [docs/finish-the-job.md](docs/finish-the-job.md) | Open-thread pickup, job receipts, capability suggestions, hardened morning brief |
| [docs/code-layout.md](docs/code-layout.md) | The four-way code layout: source repo, deployed runtime, binaries, config |
| [architecture/personalities/README.md](architecture/personalities/README.md) | Personality system: character sheets, switching rules, Parry middleware |
| [architecture/telegram-v2-spec.md](architecture/telegram-v2-spec.md) | Platform adapter spec: multi-channel message routing (Telegram, CLI, email) |

---

## License

MIT. See [LICENSE](LICENSE).

This scaffold is provided as-is for personal use and adaptation. Do not include actual credentials or personal information when sharing your own fork.
