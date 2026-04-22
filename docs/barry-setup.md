# Barry Setup — Image Generation and Visual Memory

Barry is Larry's image agent. Generates images via Venice Chat (Playwright), sorts and indexes visual material.

---

## Quick Start

```bash
# Generate image (default: Chroma, 1:1, 2x upscale)
python 03-projects/barry/barry.py "description of image"

# Quick draft (no upscale)
python 03-projects/barry/barry.py "description" --upscale 0

# Max quality
python 03-projects/barry/barry.py "description" --upscale 4

# Sort inbox
python 03-projects/barry/barry-sort.py

# Via skill
/barry-generate
```

---

## Architecture

```
User → Larry → barry.py (CLI wrapper)
  → Playwright opens Venice Chat (browser, persistent profile)
  → Prompt optimized and sent in Venice UI
  → Image generated (Chroma model, free tier)
  → Visual QA (Playwright snapshot → vision review)
    ↳ If QA fail: auto-regenerate without asking
  → Download to {{ASSETS_PATH}}/00-inbox/
  → Post-process: move, metadata, upscale
  → Backup to NAS
```

---

## File Structure

```
{{ASSETS_PATH}}/
├── venice/                 ← AI-generated images (Venice Chat)
│   ├── nsfw/               ← Privacy 3-4
│   │   ├── solo-f/
│   │   ├── solo-m/
│   │   ├── couple-mf/
│   │   ├── couple-mm/
│   │   ├── couple-ff/
│   │   ├── group-mf/
│   │   ├── toys/
│   │   └── other/
│   └── sfw/                ← Privacy 2
│       ├── portrait/
│       ├── landscape/
│       └── concept/
├── import/                 ← Imported images (photos, downloads)
│   └── [same category tree]
├── 00-inbox/               ← Drop zone — unsorted images
├── .counter                ← Global counter (next available number)
└── .trash/                 ← Trash (30-day retention)
```

Vault index (metadata notes): `03-projects/barry/visual-index/` — never image files in vault.

---

## Naming Convention

```
barry-NNNNN.{ext}
```

- 5-digit global counter: `00001`–`99999`
- Never a collision — one number per image in the entire system
- Counter stored in `{{ASSETS_PATH}}/.counter`
- Extension preserved (.png for generated, .jpg/.jpeg for imports)
- Folder determines category — not filename

---

## Model

**Default: Chroma** (free, Venice Chat UI)

- Adherence: **always 3** — never change this
- No anonymous models (cost credits, avoid)
- Venice Chat UI via Playwright — never direct API

---

## Upscale

| Flag | Behavior |
|------|---------|
| `--upscale 0` | No upscale (quick/draft/test) |
| `--upscale 2` | Default |
| `--upscale 4` | Max quality (poster/print) |

**Rule:** Upscale ONLY if user explicitly requests it. No automatic upscale.

Filename suffix: `-2x` or `-4x`. Original (1x) deleted after upscale.

Engine: Venice UI upscale (free for Pro) via Playwright. API upscale only if explicitly requested (costs credits). Settings: creativity 0.20, replication 0.70.

---

## QA Flow

1. Image generated in Venice Chat
2. Playwright takes snapshot
3. Visual review: fingers, anatomy, composition
4. On fail: auto-regenerate immediately without asking
5. On pass: proceed with download and post-processing

---

## Venice Chat Settings

Always verify BEFORE generating:
- Variants: per request
- Aspect ratio: per request (default 1:1)
- Adherence: **3** (never change)
- Model: Chroma (default)

---

## Scripts

| Script | Function |
|--------|---------|
| `barry.py` | CLI wrapper, delegates to barry-playwright.py and barry-upscale.py |
| `barry-playwright.py` | Playwright automation: Venice Chat UI → image |
| `barry-sort.py` | Vision analysis + sorting of inbox images |
| `barry-upscale.py` | Real-ESRGAN upscaling (local GPU) |
| `barry_counter.py` | Counter management |

---

## Image Categories

Allowed categories: `solo-f`, `solo-m`, `couple-mf`, `couple-mm`, `couple-ff`, `group-mf`, `group-mmm`, `group-fff`, `toys`, `portrait`, `landscape`, `concept`, `other`

Folders created on demand — no empty placeholder directories.

---

## Backup

| Layer | Source | Destination | Frequency |
|-------|--------|-------------|-----------|
| NAS | `{{ASSETS_PATH}}/` | `{{NAS_PATH}}/assets` | Every 6h (robocopy /MIR) |

Excludes: `.trash/`, `*.tmp`

---

## Privacy

NSFW images: privacy 3-4. Image files never in vault or on GitHub. Metadata notes (visual-index/) sync via Git but contain no image files.

NEVER link NSFW visual-index notes from public (L1-2) nodes.

---

## Prompt Dedup

Barry includes a prompt-hash deduplication system (`scripts/barry_dedup.py`) that prevents re-generating identical or near-identical prompts.

```bash
# Build cache from audit log
python barry_dedup.py --build

# Check a prompt
python barry_dedup.py "a fluffy cat on a sofa"
```

When integrated into the generation pipeline, Barry checks the cache before generating and prompts for confirmation if a similar prompt was used within the last 30 days. After successful generation, the prompt is registered automatically.

The cache uses SHA-256 of a normalised prompt (lowered, whitespace-collapsed, stop-words stripped) stored in `_private/image-prompt-hashes.json`.
