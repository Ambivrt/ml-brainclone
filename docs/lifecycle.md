# Information Lifecycle

Age is the wrong measure. Function decides.

A nightly system produces reports faster than anyone reads them. Reapers that archive by age alone keep the inbox finite, but they cannot tell a report that was replaced by tonight's from one that still holds an open decision, and they grow one pattern list per consumer. Five lists that drift apart is where the bugs come from.

The lifecycle engine gives every file in the scanned roots a **class** and a **verdict** from one rule file.

---

## Classes

| Class | What | Ever archived automatically |
|-------|------|----------------------------|
| `source` | anything written by the owner, notes, writing, knowledge | Never |
| `work` | drafts and material being worked on | Not in v1 |
| `consumable` | generated reports, scans, briefs, graph updates | Yes, by rule |
| `unknown` | nothing matched | Treated as `source` |

The class comes from, in order: `lifecycle:` in frontmatter, a rule in `lifecycle.yaml`, otherwise `unknown`. **The source floor is a check in the verdict function, not a rule.** No rule can switch it off: `source` and `unknown` always get `keep`.

Verdicts are `keep`, `archive` and `report`. There is no `delete`.

---

## Rules

```yaml
- pattern: '^nightly-report-(broken-links|frontmatter|orphans|tags|stale|privacy|triage)-\d{4}-\d{2}-\d{2}\.md$'
  roots: [00-inbox]
  class: consumable
  ttl_unread: 7
  ttl_read: 2
  replaced_by_newer: true
  bucket: nightly-reports
- pattern: '^kg-updates-\d{4}-\d{2}-\d{2}\.md$'
  class: consumable
  hold: [kg_open]
  bucket: kg
```

- **`replaced_by_newer`** — only for snapshots, where tonight's file makes yesterday's worthless. The prefix is everything before the date, so `triage-light` and `triage` never replace each other. Not for reports where each night holds its own content (dream logs, conflict reports, graph updates).
- **`ttl_unread` / `ttl_read`** — a read signal from the control room's file viewer (`docs/control-room.md`) separates the two. Most verdicts are decided by `ttl_unread` and replacement anyway; the read signal is there to measure how much is actually read.
- **`hold`** — named conditions that keep a file whatever its age: `kg_open` (graph lines the owner still has to decide, or a partial apply), `distillate_open` (proposals not yet accepted or skipped).
- **Roots** — only what the reapers scan: the inbox and the root of the private folder, not recursively. Tasks and the archive are never scanned. A file marked `consumable` outside the roots is never seen.

---

## Shadow first

v1 moves nothing. Each night, before any reaper has run, the engine computes its verdicts and the existing reapers' verdicts (their pure `collect()`, never `--apply`) and writes the difference to a report. The old reapers do not read the rule file during the shadow week. Switching is a separate decision after the owner has seen a week of diffs.

Tests guard the boundary: `source` and `unknown` keep regardless of rule and age; frontmatter beats a rule; files outside the roots never appear; open graph lines keep; the shadow changes no mtime and no file list in a temp vault; verdicts match the old reaper exactly except where a rule deliberately differs.

---

## Distillates

The nightly distillation writes proposals (new note, merge into an existing note, move, archive). Nothing applied them, and the file was archived after a few days with the proposals still in it. Now:

- A parser reads every format the distillation has ever written. A file where it finds zero proposals is reported as *unreadable*, never as *decided*.
- The distillation never reads earlier distillates, or held proposals would come back distilled again.
- Each open proposal becomes an item in the control room's waiting list: *Show* gives the full text, *Write* (with confirmation) writes only into the knowledge folder, *Skip* removes it. New notes get a name that exists nowhere else in the vault; merges are appended as a dated section with a link back.

---

## See also

- `scripts/inbox_reaper.py` — the current age-based reaper the engine shadows
- `docs/vault-hygiene.md` — why the inbox is a queue, never an archive bucket
