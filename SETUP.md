# Setup Guide

Step-by-step installation. Takes about 45 minutes for the full setup, 15 if you just want the basics.

---

## Prerequisites

| Component | Why | Required? |
|-----------|-----|-----------|
| **Obsidian** v1.12.4+ | Vault editor, CLI support | Yes |
| **Claude Code** | AI assistant (primary interface) | Yes |
| **Git** + GitHub account | Vault sync | Yes |
| **Python 3.10+** | Agent scripts | Yes |
| **For Barry:** Venice.ai account, Edge browser, Playwright | Image generation | Optional |
| **For Harry:** Google Cloud + Vertex AI, FFmpeg | Audio/TTS | Optional |

---

## Phase 1: Create Your Vault (~10 min)

### 1.1 Choose your vault location

Pick a location on your primary machine:

```bash
# Linux/Mac
mkdir -p ~/vault

# Windows (PowerShell)
New-Item -Path "D:\vault" -ItemType Directory -Force
```

### 1.2 Initialize Git

```bash
cd ~/vault   # or your chosen path
git init
```

### 1.3 Create the folder structure

```bash
mkdir -p {00-inbox,01-personal,02-work,03-projects,04-knowledge,05-templates,06-archive,_private}
```

Or on Windows (PowerShell):
```powershell
@("00-inbox","01-personal","02-work","03-projects","04-knowledge","05-templates","06-archive","_private") | ForEach-Object { New-Item -Path "$_" -ItemType Directory -Force }
```

### 1.4 Copy scaffold files

From this repository:

1. Copy `CLAUDE-template.md` → `CLAUDE.md` (vault root) — fill in `{{PLACEHOLDER}}` values
2. Copy `templates/` contents → `05-templates/`
3. Copy `.gitignore` → vault root
4. Copy `scripts/load-context.sh` → wherever you keep hooks

### 1.5 Create _active-context.md

Create this file in your vault root:

```markdown
# Active Context

This file is read by Claude Code at session start.
Update it regularly — it's the working memory between sessions.

## Current priorities
1. [Priority 1]
2. [Priority 2]

## Pending decisions
- [Open questions]

## Recently completed
- [Latest milestone]

## Last updated
YYYY-MM-DD
```

### 1.6 Push to GitHub

```bash
git add -A
git commit -m "Initial vault scaffold"
gh repo create my-vault --private --source . --push
```

### 1.7 Open as vault in Obsidian

Obsidian → Open folder as vault → point to your vault folder.

---

## Phase 2: Configure Tools (~20 min)

### 2.1 Activate Obsidian CLI

1. Settings → About → verify version >= 1.12.4
2. Settings → General → Command line interface → Register CLI
3. Restart terminal
4. Verify:

```bash
obsidian version
# Expected: Obsidian CLI 1.12.4+

obsidian vault
# Expected: your vault listed
```

### 2.2 Configure Claude Code

Claude Code has direct file access when you `cd` into the vault:

```bash
cd ~/vault && claude --dangerously-skip-permissions
```

**Optional: Shell alias** (add to your shell profile):

```bash
function larry() { cd ~/vault && claude --dangerously-skip-permissions "$@"; }
```

### 2.3 Configure the session init hook

In `~/.claude/settings.json`, add a SessionStart hook that reads your active context:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "bash /path/to/load-context.sh",
        "timeout": 10000
      }
    ]
  }
}
```

See `scripts/load-context.sh` for the template.

### 2.4 Install Obsidian plugins

Install via Settings → Community plugins → Browse:

| Plugin | Purpose | Settings |
|--------|---------|----------|
| **Templater** | Dynamic templates | Template folder: `05-templates/` |
| **Dataview** | Query-based views of notes | Default settings |

### 2.5 Obsidian settings

**Settings → Files & Links:**
- Default location for new notes: **In the folder specified below** → `00-inbox`
- New link format: **Shortest path when possible**

**Settings → Editor:**
- Default editing mode: **Source mode** (cleaner markdown, better for AI reading)

**Settings → Core plugins:**
- Templates: **Off** (Templater replaces it)
- Daily notes: **On** — format `YYYY-MM-DD`, folder `00-inbox`

### 2.6 Install kepano/obsidian-skills (optional)

Official Agent Skills from Steph Ango (Obsidian CEO):

```bash
cd ~/vault
mkdir -p .claude
git clone https://github.com/kepano/obsidian-skills.git .claude/obsidian-skills
```

---

## Phase 3: First Session (~10 min)

### 3.1 Start Claude Code

```bash
cd ~/vault && claude --dangerously-skip-permissions
```

### 3.2 Seed content

Prompt Claude Code:

> "Read CLAUDE.md and _active-context.md. Based on the vault structure, create starter notes: a personal profile in 01-personal/, a work overview in 02-work/, and update _active-context.md with current priorities."

### 3.3 Verify access

| Test | Command | Expected |
|------|---------|----------|
| CLI search | `obsidian search vault="my-vault" query="profile"` | Finds your profile note |
| CLI daily | `obsidian daily vault="my-vault"` | Opens/creates today's note |
| Claude Code | "Read _active-context.md" | Shows content |
| Git sync | `git push` | Pushes to GitHub |

---

## Phase 4: Set Up Agents (optional)

### 4.1 Barry (Image Agent)

See [docs/barry-setup.md](docs/barry-setup.md).

Requirements: Venice.ai account, Microsoft Edge, Playwright.

```bash
pip install playwright
playwright install msedge
```

### 4.2 Harry (Audio Agent)

See [docs/harry-setup.md](docs/harry-setup.md).

Requirements: Google Cloud account with Vertex AI, FFmpeg.

```bash
pip install google-genai
gcloud auth application-default login
```

### 4.3 Parry (Privacy Gatekeeper)

See [docs/parry-setup.md](docs/parry-setup.md) for full setup and command reference.

No external dependencies — Python stdlib only.

```bash
# Install git pre-commit hook (run once)
python 03-projects/parry/parry.py install-hooks

# Auto-tag all untagged notes with privacy level
python 03-projects/parry/parry.py tag --vault

# Check status
python 03-projects/parry/parry.py status
```

---

## Phase 5: Nightly Automation (optional)

Set up scheduled tasks to run vault maintenance overnight:

| Batch | Time | Model | Task |
|-------|------|-------|------|
| Batch 1 | 23:00 | Haiku | Vault hygiene (frontmatter, broken links, orphans) |
| Batch 2 | 01:00 | Haiku | Inbox triage (categorize, suggest connections) |
| Batch 3 | 06:00 | Haiku | Morning brief (summary + vault stats) |

Uses `scripts/collect-vault-data.sh` to gather data, then `claude --print --model haiku` to analyze.

See [docs/larry-setup.md](docs/larry-setup.md) for full nightly automation setup.

---

## Daily Workflow

### Morning
```bash
# Quick capture
obsidian daily vault="my-vault"
```

### During the day
```bash
# Append to daily note
obsidian daily:append vault="my-vault" content="- Idea about the new API design"
```

### Evening (with Claude Code)
```bash
cd ~/vault && claude --dangerously-skip-permissions
# "Process today's inbox. Move and tag notes to the right folders.
#  Update _active-context.md with current status."
```

### Weekly review
```bash
# Vault review with Claude Code
# "Scan the vault. Find orphans, duplicates, and notes that need updating."

# Tag overview
obsidian tags vault="my-vault" sort=count counts
```

---

## Multi-Machine Setup

To access your vault from another machine:

```bash
git clone git@github.com:you/my-vault.git ~/vault
cd ~/vault && claude --dangerously-skip-permissions
```

Git push/pull keeps machines in sync. No cloud drive needed.

For remote access without cloning, use Claude Code's remote capabilities (SSH into your primary machine).

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `obsidian: command not found` | CLI not registered | Settings → General → Register CLI, restart terminal |
| Claude Code can't find vault | Wrong working directory | `cd` into the vault before running `claude` |
| Git conflicts | Edited same file on two machines | Resolve manually, then commit |
| Hook not running | settings.json misconfigured | Check `~/.claude/settings.json` hook paths |
