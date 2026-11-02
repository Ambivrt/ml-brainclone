# Content Campaigns

How to manage multi-week content campaigns using the vault + Tarry + morning brief pipeline.

---

## Overview

A content campaign combines three things:

1. **Content calendar** (vault markdown) — the plan: dates, channels, topics, status
2. **Tarry release chain** (tarry-queue.json) — automated reminders that fire on schedule
3. **Morning brief integration** — pre-written content injected into the daily email, ready to copy-paste

```
content-calendar.md     tarry-queue.json        morning brief
(the plan)              (the automation)        (the delivery)
     │                       │                       │
     │  ← context refs ←     │                       │
     │                       │── fires reminder ──→   │
     │                       │   include_in_brief ──→ │
     └── status tracking ────┘                       │
                                                     ▼
                                              user copy-pastes
                                              to LinkedIn/IG/X
```

---

## Content Calendar

A markdown file in the project folder that tracks what to publish, when, and where.

### Structure

```markdown
---
tags: [project/my-launch, content/calendar]
status: active
created: 2026-04-26
privacy: 1
---

# Content Calendar — My Launch

## Week 1 (Apr 28 – May 4)

| Date | Activity | Channel | Pillar | Owner | Status |
|------|----------|---------|--------|-------|--------|
| Mon 28 | Story-first intro post | LinkedIn | Story | Owner | draft |
| Tue 29 | Curated playlist created | Spotify | Community | Owner | pending |
| Fri 2 | Weekly metrics report | Internal | Data | Larry | pending |

## Week 2 (May 5 – May 11)
...
```

### Content pillars

Rotate content across pillars to avoid monotony:

| Pillar | Weight | Purpose |
|--------|--------|---------|
| Story / Origin | 30-40% | Personal narrative, why you're doing this |
| Process / Behind the scenes | 20-25% | How it's made, tools, decisions |
| Content / The work itself | 25-30% | Excerpts, previews, deep dives |
| Community / World | 5-10% | Industry context, others' work, curation |

---

## Tarry Integration

Each week in the calendar maps to Tarry reminders. The `context` field in each reminder points back to the calendar:

```json
{
  "id": "launch-content-brief-w2",
  "fire_at": "2026-05-04T09:00:00",
  "status": "waiting",
  "message": "Content brief week 2. LinkedIn: process post Monday. Preview reveal Wednesday.",
  "context": "See content-calendar.md week 2."
}
```

For posts that need to go out on a specific day, use `include_in_brief` to inject the draft directly into the morning email:

```json
{
  "id": "launch-linkedin-first",
  "fire_at": "2026-04-28T08:00:00",
  "status": "waiting",
  "message": "LinkedIn post #1 today. Text ready in morning brief.",
  "include_in_brief": "03-projects/my-launch/linkedin-drafts/2026-04-28-first-post.md",
  "context": "Pillar: Story. No sales push, no emojis."
}
```

The morning brief (Darry or manual) reads `include_in_brief`, renders the file content inline, and the user copy-pastes directly.

---

## Draft Files

Store pre-written posts as vault notes:

```
03-projects/my-launch/
├── content-calendar.md
├── linkedin-drafts/
│   ├── 2026-04-28-first-post.md
│   ├── 2026-05-05-process-post.md
│   └── 2026-05-12-preview-post.md
└── launch-spec.md
```

Each draft has frontmatter:

```yaml
---
tags: [project/my-launch, content/linkedin]
status: draft
created: 2026-04-26
privacy: 1
publish_date: 2026-04-28
pillar: story
---
```

Status values: `draft` → `ready` → `posted` → `archived`

---

## Milestone Checks

Add periodic milestone reminders that compare actual metrics to targets:

```json
{
  "id": "launch-milestone-w4",
  "fire_at": "2026-05-23T08:00:00",
  "message": "MILESTONE CHECK week 4. Target: 50 followers, 200 streams, >10% engagement.",
  "context": "If under target: analyze why, adjust tactics. If on track: full steam."
}
```

---

## See Also

- [tarry-setup.md](tarry-setup.md) — Tarry daemon + release chain pattern
- [proactivity.md](proactivity.md) — Larry acts, doesn't just report
- [task-dispatch.md](task-dispatch.md) — Inter-agent work queue
