# Vault hygiene

A vault that an AI agent reads and writes to every day degrades differently than one only a human touches. The agent is fast, tireless and literal. It will happily write the same file to two places forever, and it will never notice, because every individual write looked correct.

These are the rules that keep it from happening, and the failures that produced them.

## One filename, one file

The same filename must never appear twice, not even in different folders with different content.

The failure mode is subtle. `2026-04-26.md` existed simultaneously as a daily note in `06-archive/daily/`, a chat log in `_private/telegram/`, and a diary page in `_private/diary/`. All three were legitimate files. None of them was a duplicate. But neither the human nor the agent could tell which was which without opening them, and wikilinks like `[[2026-04-26]]` resolved to whichever one the indexer happened to see first.

**Rule:** date files carry a type prefix.

```
06-archive/daily/daily-2026-04-26.md
_private/telegram/telegram-2026-04-26.md
_private/diary/diary-2026-04-26.md
```

The same applies to generic names. `design.md`, `report.md` and `index.md` say nothing on their own. Prefix with the project: `ambivrt-design.md`, `org-map-report.md`.

**Exception: system files.** Structural slots are exempt, because there the folder path carries the meaning and the fixed name is the point:

```
CLAUDE.md · README.md · SKILL.md · .gitkeep
architecture/personalities/<name>/character.md
architecture/personalities/<name>/prompts/text.md
```

**Enforcement.** A collision scan is cheap. Group every file by lowercased basename, drop the system names, and anything left with more than one entry is a bug:

```python
import collections, pathlib

SYSTEM = {"claude.md", "readme.md", "skill.md", ".gitkeep",
          "character.md", "text.md", "audio.md", "image.md"}

by_name = collections.defaultdict(list)
for p in pathlib.Path(".").rglob("*"):
    if p.is_file() and ".git" not in p.parts:
        by_name[p.name.lower()].append(p)

for name, paths in by_name.items():
    if len(paths) > 1 and name not in SYSTEM:
        print(name, [str(x) for x in paths])
```

Run it after any bulk move. Renaming files means fixing wikilinks in the same pass, both the bare `[[old-name]]` form and the full-path `[[folder/old-name]]` form.

## The inbox is never archived

`00-inbox/` is a queue. It gets triaged and emptied.

Archiving it to `06-archive/inbox/` feels tidy and is a mistake. It creates a folder whose name is a contradiction, it hides work that was never done, and it doubles every file: the archive gets a copy while the original sits in the inbox waiting for a sync to notice.

Three exits, no fourth:

1. Moved to a topic folder, because the content is worth keeping
2. Deleted, because it was an auto-generated report that has served its purpose
3. Acted on, then deleted

Auto-generated files should be identifiable from the filename alone so a reaper can clean them without judgment calls. Give them a `status` in frontmatter, and let `status: active` or `pinned: true` protect anything that must survive.

See `scripts/inbox_reaper.py`.

## The sync trap

This one cost real time to find, and it will hit anyone who mirrors a vault to a NAS or cloud folder.

The setup looked reasonable. A scheduled job ran every 15 minutes and did two things: pull anything that had landed directly on the NAS inbox down to local disk, then mirror the whole local vault up to the NAS.

The consequence nobody predicted: **deleting a file locally did not stick.** The mirror step had already pushed a copy to the NAS. The next pull saw a file present remotely and missing locally, and helpfully brought it back. The inbox could never be emptied. Every cleanup reverted within a quarter of an hour, and the archive filled with duplicates of files that kept reappearing in the inbox.

The first fix attempt was a `/MAXAGE` filter on the pull, so only recent files would come down. It failed, because the nightly frontmatter normalizer touched every inbox file each night. Their modification times were always fresh even when the filenames said April.

**The actual fix: do not mirror the inbox at all.** Exclude it from the upload. The remote inbox becomes what it was always meant to be — a drop box for things arriving from elsewhere, emptied by the pull step. Nothing is mirrored in, so there is nothing to resurrect.

The general principle: **a bidirectional sync over a folder you delete from will fight you.** Either the folder is authoritative locally and syncs one way out, or it is a drop box and syncs one way in. Never both.

## Two folders for the same thing

Watch for a writer that drifts away from its data.

Three instances in one vault, all found the same day:

- The nightly diary batch wrote to `_private/diary/` while 23 existing entries sat in `_private/personal/diary/`. The prompt pointed at the right path; the grading rubric pointed at the wrong one
- The daily note generator wrote to `06-archive/daily-notes/` while 73 existing notes sat in `06-archive/daily/`
- The health collector wrote to `_private/health/` while the real database sat in `_private/personal/health/`. It had lost track of the original and quietly started rebuilding from scratch — **8.87 million data points in the old file, 348 thousand in the new one**, and nothing had complained for weeks

The last one is the dangerous shape. A writer that creates a fresh empty store when it cannot find the old one fails silently and looks healthy. Every log line says success.

**Guard:** when a component owns a data file, have it assert the file exists and is non-trivial at startup rather than creating it blindly. A path that has to be created on a machine that has been running for months is a signal, not a normal case.

**Second guard:** when you move a folder, grep the codebase for the old path. Prompts, rubrics, shell scripts and Python constants all need to move together. A rename that only touches the vault leaves every writer pointing into the void.

## gitignore is not a search filter

`.gitignore` decides what syncs to a remote. It has nothing to do with what should be searchable locally.

Most search tools built on ripgrep honor `.gitignore` by default, which means a gitignored private folder becomes invisible to the agent's own search — on the machine where the agent is supposed to have full access. The agent then reports that nothing exists, confidently and wrongly.

Fix it with an `.ignore` file at the vault root. ripgrep reads it at higher precedence than `.gitignore`:

```
# Local search must not be limited by .gitignore.
!_private/
!memory/

# What should actually stay out of results — noise, not secrets:
.git/
.obsidian/
node_modules/
```

## gitignore does not untrack what was already tracked

The companion trap, and the one with real consequences.

Moving a file from a tracked folder into a gitignored one does **not** stop git from following it. `.gitignore` only applies to files git has never seen. Five personal files moved into a gitignored private folder stayed tracked across the move and were staged for push to a remote.

**Check before every push,** especially after reorganizing:

```bash
git ls-files | grep "^_private/"
```

If it returns anything, fix it before pushing:

```bash
git rm -r --cached _private/
```

The files stay on disk; git stops following them. If they already exist in unpushed commits, rewrite that history before the push rather than after — a private file that reaches a remote has to be assumed leaked, even from a private repository.

## Frontmatter is a privacy contract

Every file carries `privacy: 1-4`. Layers 1 and 2 sync to the remote, 3 and 4 stay on local disk and NAS.

That contract only holds if something enforces it. A pre-commit hook that refuses staged files in the private folder with `privacy` below 3 catches the case where a file was moved into a private folder but kept its old public frontmatter. It caught exactly that during the reorganization above.

## Recommended cadence

| When | What |
|------|------|
| Nightly, before anything else | Inbox reaper. Delete expired auto-reports so the day's triage starts from a real number |
| Nightly | Frontmatter and privacy check across the vault |
| Weekly | Filename collision scan and duplicate content hash scan |
| After any bulk move | Both scans, plus a broken wikilink check, plus `git ls-files` on private paths |
| Before every push | `git ls-files` on private paths, plus a secret scan over the commit range |

## Related

- `docs/privacy-architecture.md` — the four layers and what they mean
- `docs/system-taxonomy.md` — tags, status values, folder semantics
- `scripts/inbox_reaper.py` — the reaper described above
- `scripts/frontmatter_check.py` — frontmatter and privacy validation
