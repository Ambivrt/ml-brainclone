# Multi-LLM Inference Gateway

One harness, one memory, one writing authority — several model families.

Claude Code stays the executive harness: it owns identity, dialogue, memory and the final decision. Other LLMs (GPT via Codex CLI, Gemini via Vertex) work as **stateless specialists** behind a shared gateway. They receive bounded task packets, never file system access, and their results are advisory artifacts — never memory.

## Why

- **Epistemic diversity.** A reviewer from another model family catches bugs the author model misses. In our first pilot (20 real read-only tasks), cross-vendor review found three real privacy bugs in code written the same day, with only 2 false positives out of ~70 risk claims.
- **Resilience.** Technical failure on one provider falls back to another family — verified live when the first real Codex call failed on a schema quirk and Gemini took over seamlessly.
- **Quota separation.** Review work runs on a separate subscription, not your primary Claude quota.

## Architecture

```
Claude Code (harness, writing authority)
   └─ CLI: ask | review
        ├─ Context compiler   (explicit evidence files, size caps, dedup,
        │                      privacy = max of all sources)
        ├─ Content guard      (deterministic secret scan BEFORE dispatch:
        │                      API keys, PATs, PEM blocks, env assignments)
        ├─ Privacy gate       (per-provider max privacy level, deny by default)
        ├─ Routing policy     (YAML, schema-versioned: providers, models,
        │                      routes, per-route fallback — deterministic,
        │                      the model never picks its own provider)
        ├─ Adapters           (Codex CLI: read-only sandbox, ephemeral,
        │                      no user config; Gemini: pure API, no tools)
        ├─ Schema validation  (canonical JSON Schema, provider-side AND local;
        │                      empty or malformed output can never be success)
        └─ Result log         (append-only JSONL, file-locked, deployed-commit
                               provenance, content hashed above privacy L1)
```

## Design rules that matter

1. **Write authority is singular.** External model output is advisory. Only the harness writes to the vault, knowledge graph or event bus.
2. **Privacy is code, not prompts.** A prompt instruction is not a privacy control. The gate runs before every dispatch; unknown privacy level or provider means deny.
3. **Honest capability profiles.** A CLI-based provider with a read-only sandbox still *reads* the disk — so it is capped at low-sensitivity content in policy. Don't claim isolation you can't enforce.
4. **Fallback ≠ review.** Fallback is uptime; review is epistemic diversity. In review mode, family separation is enforced: a same-family fallback is blocked, never silent.
5. **Honest provenance.** Unknown token usage is `null`, never a fake zero. Subscription-based runs report `cost_basis: subscription` with `estimated_cost_usd: null`, not `$0.00`.
6. **Findings are classified by the harness or the human** (true positive / false positive / needs context), never by the reviewer model itself.

## Usage pattern

```
python -m lib.inference.cli review \
    --task-type code_review \
    --artifact path/to/module.py \
    --evidence path/to/contract_it_imports.py \
    --rubric "Can the fallback chain leak data to a disallowed provider?"
```

Pass the artifact's direct dependencies as explicit evidence — minimal context protects privacy but causes false positives when the reviewer can't see the contracts the code relies on. Never send the whole repo.

## Verification pattern

Ship it like infrastructure, not like a prompt. Our v1.1 gate: schema-invalid responses can't become success, secrets block before any subprocess, same-family review blocks instead of degrading silently, parallel log writers can't corrupt the JSONL, and a focused end-to-end pilot (real reviews, injected technical failure, real fallback) must pass before the gateway counts as done.
