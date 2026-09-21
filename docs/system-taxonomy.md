# System Taxonomy — Tagging & Index Pattern

How to separate **system files** (scaffold, agent infrastructure, operations) from **personal notes** in an Obsidian vault. Pattern used in Larry's vault since 2026-04-25.

## Why

A second-brain vault accumulates two very different kinds of content:

- **System** — README, LICENSE, architecture specs, agent docs, runbooks, setup guides, scripts. Configuration of the brain itself.
- **Personal** — thoughts, reflections, contacts, goals, journal entries. The actual content the brain holds.

Without a clear separation:
- Search returns infrastructure noise when you wanted notes
- Graph view becomes a tangled mess of code-adjacent files
- Personal reflections leak into system folders and vice versa
- Newcomers (or future-you) can't tell what's load-bearing vs. ephemeral

The fix is a strict tag taxonomy + a top-level index that catalogs everything system.

## Tag schema

All system files get a `system/<area>` tag. One file may have multiple system tags.

| Tag | Where | What |
|-----|-------|------|
| `system/scaffold` | Vault root | `ARCHITECTURE.md`, `README.md`, `CLAUDE.md`, `HOME.md`, `SETUP.md`, `_active-context.md` etc. |
| `system/template` | `.github/template/` | Repo bootstrap templates |
| `system/architecture` | `architecture/` | Specs, ADRs, design docs |
| `system/operations` | `operations/` | Runbooks, automation, recurring jobs |
| `system/setup` | `setup/` | Install + setup guides per tool |
| `system/skills` | `skills/` (SPEC + INDEX + patches) | Skill-system infrastructure |
| `system/bus` | `bus/` | Inter-agent event bus |
| `system/search` | `search/` | Search index infrastructure (FTS5, embeddings) |
| `system/eval` | `eval/` | Smoketest + benchmarks |
| `system/notifications` | `notifications/` | Notification routing |
| `system/agent/<name>` | `agent-folders/<name>/` | Agent-specific docs (barry, harry, parry, …) |

**Apply by path, not by content.** A script walks the vault and adds the appropriate tag based on file location. Scripts in this scaffold's `scripts/` directory provide the pattern.

## SYSTEM-INDEX

A single file at vault root catalogs all system files, grouped by category, with Dataview queries that auto-update.

See `templates/SYSTEM-INDEX.md` in this scaffold.

The index serves three purposes:

1. **Discovery** — newcomers (or future-you) find every system file from one place
2. **Wikilink graph** — every system file gets at least one inbound link, killing orphans
3. **Live counts** — Dataview shows file count per category; growth is visible

Linked from `HOME.md` so it appears in the daily-use dashboard.

## What does NOT get tagged

- Personal notes, journal entries, reflections — kept in `01-personal/` or `_private/`
- Domain knowledge files — `04-knowledge/` stays untouched
- Daily notes, `00-inbox/YYYY-MM-DD.md` are personal, if you use them at all. The reference system retired daily notes in September 2026 in favor of a code-generated status file; see [docs/status-file.md](status-file.md)
- Project content (creative work, customer files) — has its own project tags (`project/<name>`), not system tags
- Vendored dependencies — `bin/`, `.venv/`, `node_modules/` should be in `.gitignore` AND excluded from Obsidian via `userIgnoreFilters` in `.obsidian/app.json`

## Excluding noise from Obsidian

Edit `.obsidian/app.json`:

```json
{
  "userIgnoreFilters": [
    "path/to/bin/",
    "path/to/.venv/",
    ".playwright-mcp/",
    "operations/.data/"
  ]
}
```

This hides matching paths from graph view, search, autocomplete, and Dataview. Reload Obsidian after editing.

## Migration playbook

For an existing vault that needs the taxonomy:

1. **Survey** — list folders that hold system content vs. personal content. Decide tag mapping.
2. **Run path-based tagger** (see `scripts/system_tag_batch.py` in scaffold). Adds `system/<area>` tags to files based on path. Idempotent — re-runs are safe.
3. **Review skipped files** — files without frontmatter need it added before tagging works.
4. **Build SYSTEM-INDEX** — copy template, customize categories, add to `HOME.md`.
5. **Configure Obsidian ignore filters** — exclude `bin/`, `.venv/`, runtime data folders.
6. **Verify** — open SYSTEM-INDEX, confirm Dataview counts make sense.

## Maintenance

- Re-run the tag batch quarterly or after big infrastructure changes — picks up new files automatically.
- Add new categories to the Dataview query in SYSTEM-INDEX as the system grows.
- If a file ever has both `system/*` and personal-content tags, decide which it really is and move/retag.
