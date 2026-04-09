# Parry Setup — Privacy Gatekeeper

Parry is Larry's fourth agent. Not a modality (image/audio/text) but a **filter layer** that sits between Larry and the outside world.

- **Larry** — thinks, plans, orchestrates
- **Barry** — sees (images)
- **Harry** — hears and speaks (audio)
- **Parry** — guards, filters, judges

---

## What Parry Does

| Domain | Function |
|--------|----------|
| Privacy Guardian | Enforces L1–L4 separation, blocks violations before they happen |
| Tone & Voice | Checks channel-appropriate tone, learns your style per recipient |
| Quality Gate | ÅÄÖ, trailing whitespace, API key detection |
| Auto-tagging | Infers and writes `privacy:` frontmatter on untagged notes |

---

## Quick Start

```bash
# Install git hook (run once)
python 03-projects/parry/parry.py install-hooks

# Check current mode
python 03-projects/parry/parry.py status

# Scan a file
python 03-projects/parry/parry.py scan path/to/note.md

# Tag all untagged notes
python 03-projects/parry/parry.py tag --vault
```

No external dependencies — Python stdlib only.

---

## Installation

1. Copy `parry.py` to `03-projects/parry/parry.py` in your vault.
2. Run `parry install-hooks` to activate the git pre-commit hook.
3. Optionally add a shell alias:

```bash
# In .bashrc or PowerShell profile:
alias parry="python /path/to/vault/03-projects/parry/parry.py"
```

---

## Modes

| Mode | Behavior |
|------|----------|
| `off` | Zero filtering. Everything passes. |
| `relaxed` | Default outside work hours. Only hard L3/L4 violations blocked. |
| `balanced` | Work hours. NSFW flagged, tone checked on professional channels. |
| `strict` | Everything reviewed. Use before client meetings or demos. |

```bash
parry off          # Turn off ("gå och basta")
parry on           # Back to balanced/relaxed (schedule-based)
parry strict       # Strict mode
parry status       # Show current mode, schedule, context
```

The mode switches automatically based on schedule. `balanced` activates during configured work hours, `relaxed` at all other times. Override manually at any time.

---

## Schedule

```bash
parry schedule                           # Show current schedule
parry schedule --work "mon-fri 09-17"   # Set work hours
parry vacation --add 2026-07-01 2026-07-31
parry vacation --clear
```

Swedish public holidays are automatically detected — Parry switches to `relaxed` on those days.

---

## Privacy Commands

### Scan

```bash
parry scan path/to/file.md    # Scan a single file
parry scan --staged            # Scan git staged changes (used by pre-commit hook)
parry audit                    # Scan entire vault
```

Exits with code 1 if violations are found — the pre-commit hook uses this to block commits.

### Auto-Tagging

Parry infers the correct privacy level from file content:

| Signal | Level |
|--------|-------|
| File in `_private/` | L3 |
| API key detected | L3 |
| NSFW keywords | L3 |
| Health / finance / relationship keywords | L3 |
| Work / client / professional keywords | L2 |
| Default | L1 |

```bash
parry tag path/to/note.md     # Tag single file (skips if already tagged)
parry tag --vault              # Tag all untagged .md files in vault
parry tag --vault --dry-run   # Preview without writing
```

---

## Tone Commands

### Gate (general)

```bash
parry gate --channel linkedin --content "text"
parry gate --channel gmail-work --recipient magnus-werner --content "text"
```

Available channels: `linkedin`, `gmail-work`, `gmail-personal`, `reddit`, `vault`, `casual`

### Check-mail (pre-send wrapper)

```bash
parry check-mail --recipient ana --content "Hej Ana..."
parry check-mail --recipient kund --content "Hej, angående uppdraget..."
```

Routes to `gmail-personal` or `gmail-work` automatically based on recipient. Exits 1 if blocked.

---

## Tone Learning

Parry learns your communication style per recipient. Feed it real messages:

```bash
parry learn --recipient ana --content "full message text"
parry learn --recipient bengan --channel gmail-personal --content "..."
```

After **5+ observations** per recipient, Parry automatically flags deviations in `check_tone` and `check-mail`:

- Formality shift (more than 3 points on a 0–10 scale)
- Unusual length (more than 3× or less than 20% of established average)
- New greeting phrase (not seen before for this recipient)

Observations are stored in `.parry-tone-memory.json` (max 50 per recipient).

Built-in recipient profiles (no learning required): `ana`, `bengan`, `miza`, `kund`, `magnus-werner`, `linus-lindh`

---

## Pre-Commit Hook

The git hook runs `parry scan --staged` on every commit attempt. If violations are found, the commit is blocked.

```bash
parry install-hooks    # Install (or reinstall) the hook
```

The hook is written to `.git/hooks/pre-commit`. To bypass in an emergency:
```bash
git commit --no-verify -m "..."    # Skip all hooks
```

---

## State Files

| File | Purpose |
|------|---------|
| `.parry-state.json` | Current mode, schedule, vacation periods |
| `.parry-tone-memory.json` | Tone observations per recipient |

Both are in `03-projects/parry/`. Add to `.gitignore` if the vault is public.

---

## See Also

- [privacy-architecture.md](privacy-architecture.md) — Privacy model Parry enforces
- [larry-setup.md](larry-setup.md) — Larry configuration
- [architecture-overview.md](architecture-overview.md) — System overview
