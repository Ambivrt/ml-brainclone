# Farry Setup -- Universal Interpreter

Farry is the ecosystem's language and format service: live translation, machine translation, and structural format conversion. There is no video agent in this ecosystem; if you came here looking for one, it does not exist.

- **Larry** -- thinks, plans, orchestrates
- **Barry** -- sees (images)
- **Harry** -- hears and speaks (audio)
- **Garry** -- shapes (3D)
- **Farry** -- understands all languages

---

## Status: Live

Farry is an active service, invoked on demand.

---

## What Farry Does

| Domain | Function |
|--------|----------|
| Live translation | "Babel fish" mode: real-time translation of spoken or typed conversation |
| Machine translation | Batch translation of documents, messages, notes |
| Format conversion | Structural conversion between json, yaml, toml, xml, csv |
| Terminology consistency | Checks memory first, so a name or term translates the same way every time |

Farry does not do video. It does not do image or audio generation, those belong to Barry and Harry.

---

## Architecture

Farry runs as an on-demand session, similar to Garry. Larry invokes it when a task needs translation or format conversion.

```
User request ("translate this live" / "convert this to yaml")
        |
        v
Larry receives message
        |
        v
Farry invoked (on-demand session)
        |
        v
Memory checked first for consistent terminology
        |
        v
Translation / conversion performed
        |
        v
Result returned to Larry -> user
```

---

## Technology

| Component | Role |
|-----------|------|
| **Model call** | Resolved from the one model-tier file, never hardcoded. See [model-tiering.md](model-tiering.md) |
| **Memory check** | Queries Milla for established terminology before translating a name or term |
| **Bus integration** | Posts results as bus events for other agents to consume |
| **Vault logging** | Translation and conversion results stored as vault notes when they matter beyond the conversation |

---

## Integration Points

- **Larry**: Invokes Farry for translation and format-conversion tasks, receives structured results
- **Milla**: Farry checks memory before translating so terminology stays consistent across languages
- **Brains Bus**: Posts translation/conversion events for downstream processing

---

## Prerequisites

| Component | Required? | Notes |
|-----------|-----------|-------|
| **Text model access** | Yes | Whatever model family your tier file resolves to |
| **Milla / MemPalace** | Recommended | For terminology consistency checks |

---

## Installation

1. Copy the Farry script to `03-projects/ml-brainclone/agents/farry.py`.
2. Register Farry as an on-demand session (not continuous) in your daemon-manager.
3. Add bus event routing for translation/conversion event kinds.
4. Point model resolution at your tier file (`model-tiering.md`), never a hardcoded model name.

---

## See Also

- [larry-setup.md](larry-setup.md) -- Larry (Claude Code) configuration
- [garry-setup.md](garry-setup.md) -- Garry spatial agent (similar on-demand pattern)
- [harry-setup.md](harry-setup.md) -- Harry audio agent
- [model-tiering.md](model-tiering.md) -- Model tier file and resolver functions
- [agent-capabilities.md](agent-capabilities.md) -- Capability matrix for all agents
