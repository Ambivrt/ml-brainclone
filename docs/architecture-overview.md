# Larry Ecosystem — Architecture Overview

A personal AI second brain consisting of four agents (Larry, Barry, Harry, Parry) orchestrated via Claude Code and an Obsidian vault. Runs locally on a personal machine.

---

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                         THE USER                               │
└──────────────────────────┬─────────────────────────────────────┘
                           │ (Claude Code CLI / shell)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                    LARRY (Claude Code)                         │
│  Orchestrator · Text · Knowledge · Memory · Planning           │
│                                                                │
│  CLAUDE.md (rules) + _active-context.md (status)              │
│  MEMORY.md (persistent memories) + Skills (.claude/commands/)  │
│  Hooks (SessionStart: load-context.sh)                         │
└──┬──────────┬───────────┬──────────────┬────────────────────┬──┘
   │          │           │              │                    │
   ▼          ▼           ▼              ▼                    ▼
BARRY       HARRY       PARRY         GWS CLI           Obsidian CLI
(Image)     (Audio)   (Gatekeeper)  (Gmail/Cal/Drive)   (Vault ops)
   │          │           │
   ▼          ▼           ▼
Venice     Gemini     Privacy/Tone/
Studio     TTS +      Quality scan
(Playwright) FFmpeg
   │          │
   ▼          ▼
{{ASSETS_PATH}}  {{AUDIO_PATH}}
(Images)         (Audio)
```

---

## Agents

| Agent | Modality | Primary function | Core technology |
|-------|----------|-----------------|-----------------|
| **Larry** | Text | Orchestrator, knowledge, planning | Claude (Sonnet/Opus via Claude Code) |
| **Barry** | Image | Generation, sorting, visual memory | Venice Studio via Playwright (browser) |
| **Harry** | Audio | TTS, music, SFX, mixing | Gemini TTS (Vertex AI) + FFmpeg |
| **Parry** | Filter | Privacy, tone, quality control | parry.py (Python middleware) |

---

## Data Flows

### Image Generation (Barry)
```
User → Larry → barry.py → Playwright (Venice Studio UI)
  → Image generated → Downloaded to {{ASSETS_PATH}}/00-inbox/
  → QA review (Playwright snapshot + vision check)
  → Upscale via barry-upscale.py (Real-ESRGAN, local GPU)
  → Move to correct category (venice/nsfw/ or venice/sfw/)
  → Metadata note created in vault (visual-index/)
  → Backup to NAS (robocopy /MIR, every 6h)
```

### TTS (Harry)
```
User → Larry → harry-tts.py "file.md"
  → parse_voice_markup() → segment per ::voice[name]
  → Gemini TTS API (Vertex AI, GCP project: {{GCP_PROJECT}})
  → PCM data (24kHz, 16-bit, mono) per segment
  → concat_wav_segments() → combined WAV
  → FFmpeg: atempo (speed) + libmp3lame → MP3 192kbps
  → Saved to {{AUDIO_PATH}}/01-tts/
  → log_cost() → cost-log.csv
  → Backup to NAS (every 6h)
```

### Nightly automation
```
OS Task Scheduler
  → nattskift-runner.sh (bash)
    → collect-vault-data.sh (collects vault data)
    → claude --print --model haiku < prompts/batchN.md
    → Output → 00-inbox/nightly-report-*.md
```

### Mail and calendar
```
User → Larry → gws gmail / gws calendar / gws drive
  → Parry gate (tone + privacy) → Send/archive/fetch
```

---

## Filesystem

| Location | Content | Sync |
|----------|---------|------|
| `{{VAULT_PATH}}/` | Vault (Obsidian markdown) | Git → {{GITHUB_REPO}} |
| `{{ASSETS_PATH}}/` | Images (never in vault) | NAS backup (robocopy) |
| `{{AUDIO_PATH}}/` | Audio files | NAS backup (robocopy) |
| `{{VAULT_PATH}}/../playwright-profile/` | Browser profile (cookies) | Local only |
| `~/.claude/` | Claude Code config, memory, hooks | Local only |

---

## Memory System

```
~/.claude/projects/{{VAULT_SLUG}}/memory/
├── MEMORY.md          ← Index + active memories
├── user/              ← Facts about the user
├── feedback/          ← Learned behavioral preferences
├── project/           ← Active project memories
└── reference/         ← Technical reference memories
```

Memories persist across sessions. Created and updated by Larry during conversation.

---

## Privacy Layers

| Level | Name | Content | Location |
|-------|------|---------|----------|
| L1 | Public | Public info, work content | Vault root |
| L2 | Personal | Private but not sensitive | Vault root |
| L3 | Private | Sensitive (health, finance, etc.) | `_private/` |
| L4 | Unconscious | Deeply personal, AI observations | `_private/` |

Parry enforces that L3-4 content never leaks to L1-2 destinations.

---

## Model Routing (Family Model)

| Model | Alias | Usage |
|-------|-------|-------|
| Claude Haiku | "Hakke" | Nightly tasks, routine operations, fast responses |
| Claude Sonnet | "Sonny" | Daily notes, triage, standard work |
| Claude Opus | "Opus" | Architecture, strategy, deep analysis |
| Claude Opus 1M | "Opus Max" | Mega-sessions, full vault analysis |

Fallback on guardrail refusal: Venice (DeepSeek/Qwen, E2EE).

---

## Nightly Automation

All batches run between 01:00–06:00 only.

| Batch | Time | Model | Task |
|-------|------|-------|------|
| Batch 1 | 01:00 | Haiku | Vault hygiene (frontmatter, broken links, orphans) |
| Batch 2 | 02:00 | Haiku | Inbox analysis (triage, connection suggestions, stale check) |
| Batch 3 | 03:00 | Haiku | Reddit/community monitoring (L1-2 only) |
| Batch 4 | 04:00 | System | Milla mine — reindex vault (GPU-heavy, never run manually during active session) |
| Batch 5 | 06:00 | Haiku | Morning brief (summary + vault stats + Reddit digest) |

---

## Core Principles

1. **Larry orchestrates** — Barry and Harry called by Larry on demand
2. **Best model first** — primary model first, fallback only on guardrail refusal
3. **Privacy is configuration** — levels control which models MAY be used
4. **Vault is text-only** — no binary files. Images → assets, Audio → audio
5. **Robust over quick** — never a hack, always a reliable solution
6. **Yolo mode** — Larry always runs with `--dangerously-skip-permissions`
7. **Parry guards** — middleware filter on all output, three modes: off/balanced/strict

See [Larry's Ten Commandments](ten-commandments.md) for the full operating principles.
