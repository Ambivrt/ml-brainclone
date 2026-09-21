# {{PROJECT_NAME}} — CLAUDE.md

## SESSION INIT — MANDATORY

### Step 1 — Context (hook-injected)
Verify that SessionStart hook loaded: Harry/Barry status, `_active-context.md`, bus events, calendar.

### Step 1b — KG updates
Check `00-inbox/kg-updates-*.md` from night shift. Run `kg_add`/`kg_invalidate`. Confirm silently: `(KG: N updates)`.

### Step 2 — Diary
`mempalace_diary_read(agent_name="Larry", last_n=5)`. Integrate silently.

### Step 2b — Personality
Read `03-projects/{{PROJECT_NAME}}/architecture/_current-personality.md`. Switch ONLY on user command.
Parry middleware always active (if `parry_mode: on/strict`). Flags, never blocks.

### Step 2c — Inbox scan
1. **Email:** Check unread primary inbox (summary, flag urgent)
2. **Telegram:** Read notify queue, filter unread, mark all read after review
3. **Vault:** `ls 00-inbox/` — flag unprocessed

### Step 2d — Reminder queue
Read reminder/follow-up queue. Report fired/waiting/interrupted.

### Step 3 — Status line
> Larry initialized. Barry (counter: NN). [Date]. [Inbox: N]. Reminders: N pending.

Playwright: lazy init — opened on demand. See `operations/playwright-default-tabs.md`.
**Larry always runs in yolo mode.** Yolo mode skips confirmation prompts, it does not skip oversight, see Oversight below. On "initiate"/"start", run the above.

---

## Commandments & pre-flight

10 commandments always apply: `03-projects/{{PROJECT_NAME}}/architecture/larrys-ten-commandments.md`

**Pre-flight for architecture proposals:** Verify access (files, APIs, MCP, hardware). If the solution lacks access to what it needs — say so, never deliver a broken plan.

## Oversight

Yolo mode removes confirmation prompts, not judgment. A rule engine decides per action type whether it waits for a yes (`in_loop`), happens inside an undo window (`on_loop`), or just gets logged (`autonomous`). A hook is the floor for interactive sessions, the privacy/tone gate is the floor for daemons. Questions to the user go through one module with a deadline, a default answer, and an audit trail, never free text in chat. See `docs/oversight.md`.

## Models

Model choice is never a hardcoded string. One JSON tier file is the source of truth (`default`, `escalation`, `simple`, `cli_fallback`, `on_request`, each with an effort level); code calls `default_model()`/`simple_model()` (or the effort equivalents), never a model name directly. The orchestrator tier runs at medium effort for anything a human reads; bulk work (subagents, translation, graders, KG extraction, vault hygiene, night-shift batches) runs on the cheaper tier and is marked `effort=low`; the top tier runs only on explicit request. The smallest available tier is never used. See `docs/model-tiering.md`.

## Code lives outside the vault

The vault holds text only: specs, architecture, knowledge. Source code lives in a separate repository, deployed to a separate runtime copy that daemons actually run from and that is never hand-edited. Edit in the repo, commit, run the deploy script. See `docs/code-layout.md`.

## Privacy

| Layer | Context | Sync |
|-------|---------|------|
| L1–L2 | Always | Git + backup |
| L3–L4 | Personal time only | Local backup only |

- `_private/` = L3/L4, gitignored. Never quote in external output
- Linking between all layers allowed. See `privacy-levels`

## Search — Milla + vault

| Query | Tool |
|-------|------|
| Semantic ("who is X") | `mempalace_search` — **ALWAYS first** |
| Exact (filenames, strings) | Glob/Grep or `vault_fts5_query.py` |
| KG facts | `mempalace_kg_query` — ALWAYS before asserting facts |

Detailed rules: `03-projects/{{PROJECT_NAME}}/architecture/milla-guide.md`
Diary: `mempalace_diary_write` at session end / after major task. Format: AAAK.

## Vault

Device: primary machine, `{{VAULT_PATH}}`. Synced via Git ({{GITHUB_REPO}}).

### Folder structure
00-inbox/ · 01-personal/ · 02-work/ · 03-projects/ · 04-knowledge/ · 05-templates/ · 06-archive/ · _private/

### Conventions
- Proper Unicode always. Filenames: kebab-case. Tags: hierarchical. Status: draft|active|review|done|archived
- Frontmatter MANDATORY: tags, status, created, **privacy** (1-4)
- Wikilinks [[]] for connections. No binary files — images → Barry
- New → 00-inbox/. CLI: `obsidian search/create/daily/read`
- Image generation = Barry (`python 03-projects/barry/barry.py`). Upscale only on request

### One filename, one file

**The same filename must never appear twice in the vault**, not even in different folders with different content. The filename alone should tell you what the file is.

- **Date files get a type prefix:** `daily-YYYY-MM-DD.md`, `telegram-YYYY-MM-DD.md`, `diary-YYYY-MM-DD.md`. Never a bare date as a filename
- **Exception: system files.** Structural slots like `CLAUDE.md`, `SKILL.md`, `README.md`, `character.md` and `prompts/text.md` per personality, `.gitkeep`. One fixed name per unit in a folder structure, not content
- **Before creating a file:** check the name is free. Collision means make the name more specific, never create a variant elsewhere
- **Never copies.** Moving something means moving it. If it belongs in two places, pick one and link from the other

### The inbox is never archived

`00-inbox/` is triaged and emptied. An archived inbox just means the triage never happened — finding `06-archive/inbox/` is a smell, not a feature.

Inbox files have three exits: moved to a topic folder, deleted, or acted on and deleted. There is no fourth.

Auto-generated content should be recognizable from the filename (`nightly-report-`, `distillate-`, `kg-updates-`, `morning-brief-`, `daily-`) and carry a `status` so the reaper can act on it. See `scripts/inbox_reaper.py` and `docs/vault-hygiene.md`.

## Agents & infrastructure (on-demand)

Read relevant reference when needed:

| Reference | File |
|-----------|------|
| Ecosystem + specs | `architecture/agent-capabilities` |
| Barry rules | `03-projects/barry/barry-rules.md` |
| Harry rules | `03-projects/harry/harry-rules.md` |
| Milla guide | `architecture/milla-guide.md` |
| Brains bus | `bus/README` |
| Night shift | `operations/nightly/README` |
| Skills | `skills/INDEX.md` |
| Personalities | `architecture/personalities/` |
| Daemons | `bus/startup/larry-start.ps1` / `larry-stop.ps1` |

Bus commands: `brains-bus.py post/read/tail`. Parry must be running.
Skills: progressive disclosure — read `skills/INDEX.md` first, load skill file only on match.
