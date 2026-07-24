# Telegram v2 — Technical Spec

> Replace `claude -p` subprocess with Anthropic SDK directly in the listener.
> The bot stops cosplaying — and becomes the real brain.
> **Part of the PWA** — the Telegram bot becomes a backend module, not a standalone daemon.

**Status:** Parked — design phase (decisions first, implementation later)
**Connections:** Platform adapter spec (`architecture/platform-adapter-spec.md`)

> **Note:** The platform adapter spec provides the abstraction v2 needs to support Signal/Matrix/Discord alongside Telegram. Adapter implementation happens as part of the v2 build — not separately.

---

## 1. The Problem

Current `_larry_reply()` runs `claude -p` from a neutral directory — deliberately without CLAUDE.md, without vault access, without semantic memory, without personalities. The result:

| Missing today | Consequence |
|---------------|-----------|
| Vault access | Cannot reference notes, projects, context |
| Semantic memory (MemPalace) | No semantic search, no knowledge graph |
| Personality system | Hardcoded 15-line system prompt instead of character sheets |
| Tools | Naked text-in/text-out, no tool use |
| Deep history | 10 messages, flat JSON |
| Model selection | Always the same model, no routing |
| Privacy middleware | No privacy gate |
| Session continuity | Zero connection to Claude Code sessions |

The Telegram bot ≠ the brain. It's a cosplayer with the right accent but the wrong content.

---

## 2. Goals

**The Telegram interface should be the same brain** — same intelligence, same memory, same voice, same context. The limitation is only the interface (text/voice instead of CLI), not the brain.

### Principles
1. **Same brain** — Anthropic SDK directly, not subprocess
2. **Same memory** — Semantic search injected into context per message
3. **Same voice** — Full personality prompt, not compressed
4. **Same context** — Vault files read on-demand, active-context always loaded
5. **Cost control** — Prompt caching, model selection per situation, budget cap
6. **Robustness** — Everything that works today (watchdog, PID lock, heartbeat) stays

---

## 3. Architecture

### 3.0 Place in the Ecosystem — PWA

The Telegram bot is NOT a standalone daemon going forward. It becomes a **backend module** in the PWA:

```
┌─────────────────────────────────────────────────────────┐
│ PWA                                                     │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Chat-view│  │Image-view│  │Audio-view│  (frontend)   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│  ┌────┴──────────────┴──────────────┴────┐              │
│  │            API layer (FastAPI?)       │              │
│  └────┬──────────────┬──────────────┬────┘              │
│       │              │              │                    │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴────┐              │
│  │  Brain   │  │  Barry   │  │  Harry   │  (backends)   │
│  └────┬─────┘  └──────────┘  └──────────┘              │
│       │                                                 │
│  ┌────┴─────────────────────────────────┐              │
│  │ Interfaces (all talk to the same     │              │
│  │ Brain):                              │              │
│  │  • PWA chat view (websocket)         │              │
│  │  • Telegram bot (long-poll)          │              │
│  │  • CLI (Claude Code — existing)      │              │
│  └──────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

**Key insight:** The `Brain` class is interface-agnostic. Telegram, the PWA chat, and (potentially) CLI all talk to the same brain. The Telegram listener becomes a thin adapter that receives updates and sends responses — all intelligence lives in `Brain`.

### 3.1 Brain — Anthropic SDK Client

Replaces `subprocess.run(["claude", "-p", ...])` with `anthropic.Anthropic()`.

```
┌─────────────────────────────────────────────────────┐
│ Brain (interface-agnostic)                          │
│                                                     │
│  reply(text, context) → str                         │
│       │                                             │
│       ├── system_prompt_builder()                   │
│       │     ├── personality (character + prompts)   │
│       │     ├── voice profile                       │
│       │     ├── active-context (cached)             │
│       │     ├── interface-specific rules            │
│       │     └── privacy middleware prompt            │
│       │                                             │
│       ├── context_injector()                        │
│       │     ├── Semantic memory search              │
│       │     ├── KG query (entity context)           │
│       │     ├── Conversation history                │
│       │     └── Vault files (on-demand)             │
│       │                                             │
│       ├── anthropic.messages.create()               │
│       │     ├── model: configurable                 │
│       │     ├── max_tokens: 1024 (text) / 512 (voice)│
│       │     ├── system: [cacheable blocks]          │
│       │     └── messages: history + new             │
│       │                                             │
│       └── response → str (plain text)               │
│                                                     │
│  Interface adapters (thin):                         │
│  ├── TelegramAdapter — long-poll, TTS, photo/voice  │
│  ├── PWAAdapter — websocket, streaming              │
│  └── (future: CLIAdapter, VoiceAdapter)             │
└─────────────────────────────────────────────────────┘
```

### 3.2 System Prompt — Construction

The system prompt is built in cacheable blocks (Anthropic prompt caching):

| Block | Content | Cache | Size (approx) |
|-------|---------|-------|---------------|
| **1. Personality** | character sheet + text prompt + voice profile | Static — cache breakpoint | ~3,000 tokens |
| **2. Interface rules** | Telegram/PWA limitations, TTS awareness | Static | ~500 tokens |
| **3. Active context** | Working memory — reloaded every 15 min | Ephemeral cache (5 min) | ~2,000 tokens |
| **4. Privacy middleware** | Privacy rules, destructive-action guard | Static | ~300 tokens |

**Total system prompt:** ~6,000 tokens (of which ~3,500 statically cached).

### 3.3 Context Injection Per Message

Before each `messages.create()`, relevant context is injected as user messages:

```python
def _build_messages(new_text: str) -> list[dict]:
    messages = []

    # 1. Semantic memory search if message references something
    memory_context = _memory_search(new_text)
    if memory_context:
        messages.append({
            "role": "user",
            "content": f"[CONTEXT FROM MEMORY]\n{memory_context}"
        })
        messages.append({
            "role": "assistant",
            "content": "Noted."
        })

    # 2. Conversation history
    for entry in _load_history():
        role = "user" if entry["role"] == "user" else "assistant"
        messages.append({"role": role, "content": entry["text"]})

    # 3. New message
    messages.append({"role": "user", "content": new_text})

    return messages
```

### 3.4 Semantic Memory Integration

The semantic memory system runs as a local Python import (not MCP).

```python
from mempalace import MemPalace

palace = MemPalace()

def _memory_search(text: str) -> str | None:
    """Semantic search + KG lookup. Returns context string or None."""
    results = palace.search(text, top_k=3, exclude_rooms=["daily"])
    kg_hits = palace.kg_query(text)  # entity match

    if not results and not kg_hits:
        return None

    parts = []
    if results:
        for r in results:
            parts.append(f"- [{r.room}] {r.title}: {r.snippet}")
    if kg_hits:
        for triple in kg_hits:
            parts.append(f"- KG: {triple.subject} → {triple.predicate} → {triple.object}")

    return "\n".join(parts)
```

**Trigger logic:** Not every message needs a memory search.

| Message type | Search? |
|--------------|---------|
| Short conversational ("ok", "nice", "yeah") | No |
| Question ("what did we say about...", "who is...") | Always |
| Reference to project/person | Always |
| Casual chat without reference | No |
| Voice message (transcription) | If >10 words |

Heuristic: `len(text.split()) > 5 and any(trigger in text.lower() for trigger in SEARCH_TRIGGERS)`.
Complement with question-word matching.

### 3.5 Model Selection

| Situation | Model | Why |
|-----------|-------|-----|
| Default text conversation | `<mid-tier-model>` | Fast, cheap, good enough |
| Complex question (long, references context) | `<mid-tier-model>` | Sufficient |
| Creative / emotional / deep | `<top-tier-model>` | Depth needed |
| Simple ack / short reply | `claude-haiku-4-5-20251001` | Fastest, cheapest |

**Model selection logic:**
```python
def _pick_model(text: str, sentiment: str) -> str:
    words = len(text.split())
    if words <= 3:
        return "claude-haiku-4-5-20251001"
    if sentiment in ("sad", "angry") or any(kw in text.lower() for kw in DEEP_KEYWORDS):
        return "<top-tier-model>"
    return "<mid-tier-model>"
```

`DEEP_KEYWORDS` should be configured per deployment — topics that require deeper reasoning (creative writing, emotional support, complex analysis).

### 3.6 Conversation History — Upgrade

**Current:** 10 messages, flat JSON, no metadata.

**New:**

```python
@dataclass
class Message:
    role: str           # "user" | "assistant"
    text: str
    timestamp: datetime
    sentiment: str      # "neutral", "happy", etc.
    model: str          # which model replied
    has_memory: bool    # if memory context was injected
    voice: bool         # if it was a voice message

MAX_HISTORY = 30        # more messages, but...
MAX_CONTEXT_TOKENS = 4000  # ...bounded by tokens, not count
```

**Token budgeting:** Conversation history is truncated from the back (oldest first) when it exceeds `MAX_CONTEXT_TOKENS`. Newest messages always take priority.

### 3.7 Telegram-Specific System Prompt

What distinguishes the Telegram interface from the CLI interface:

```
TELEGRAM-SPECIFIC:
- You are responding via Telegram. The user reads on their phone.
- Short replies. 1-3 sentences. Sometimes one word.
- The user hears your voice (TTS). Write as it should SOUND.
- You do NOT have access to: filesystem, git, Playwright, Barry, Harry.
- You CAN: search semantic memory, read vault notes, query KG.
- If the user asks for something you can't do: "Run that in the CC session."
- Never code blocks unless explicitly needed.
- Never lists unless explicitly needed.
- Natural flow. Rhythm. Pauses via punctuation.
```

### 3.8 Personality Integration

The Brain class loads personality dynamically from vault files:

```python
def _load_personality(self) -> str:
    """Load active personality from vault."""
    current = self._read_vault_file("architecture/_current-personality.md")
    personality_name = _parse_frontmatter(current).get("personality", "default")

    character = self._read_vault_file(
        f"architecture/personalities/{personality_name}/character.md"
    )
    text_prompt = self._read_vault_file(
        f"architecture/personalities/{personality_name}/prompts/text.md"
    )
    voice_profile = self._read_vault_file("voice-profile.md")

    return f"{character}\n\n{text_prompt}\n\n{voice_profile}"
```

Personality switching via `/personality <name>` command reloads the system prompt and invalidates the prompt cache.

---

## 4. Existing Features — What Stays

Everything that works today is preserved unchanged:

| Feature | Status | Change |
|---------|--------|--------|
| Telegram long-polling | Unchanged | — |
| PID file lock | Unchanged | — |
| Watchdog + exponential backoff | Unchanged | — |
| Heartbeat file | Unchanged | — |
| `/status`, `/stop`, `/uptime`, `/queue`, `/clearqueue` | Extended | New commands added |
| `/voice` toggle | Unchanged | — |
| Gemini TTS | Unchanged | — |
| Sentiment-based prosody | Upgraded | See 5.2 |
| Photo reception + Gemini vision | Unchanged | — |
| Voice reception + Gemini STT | Unchanged | — |
| Daily Telegram log | Unchanged | — |
| notify-queue.json | Unchanged | — |
| Callback handling (approve/edit/skip) | Unchanged | — |
| Health check daemon | Unchanged | — |
| Notification helper (larry_notify.py) | Unchanged | — |
| Startup/shutdown notification | Unchanged | — |
| is_bot guard | Unchanged | — |

---

## 5. New Features

### 5.1 New Commands

| Command | Function |
|---------|---------|
| `/model` | Show/switch active model. `/model opus`, `/model sonnet`, `/model haiku`, `/model auto` |
| `/context` | Show current state: active personality, history length, last memory search |
| `/forget` | Clear conversation history. Start with clean context |
| `/memory <query>` | Explicit semantic memory search, returns results directly |
| `/personality <name>` | Switch personality via Telegram (requires character sheets) |
| `/cost` | Show approximate session cost (input/output tokens x price) |

### 5.2 Sentiment Analysis — Upgrade

Current: keyword matching (`if "damn" in text: return "frustrated"`).

**New:** Use Haiku for sentiment classification as a separate cheap call:

```python
async def _analyze_sentiment_llm(text: str) -> str:
    """Haiku-based sentiment analysis. ~$0.001 per call."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        system="Analyze sentiment. Reply with ONE word: happy/excited/playful/frustrated/sad/angry/curious/tired/neutral",
        messages=[{"role": "user", "content": text}],
    )
    return response.content[0].text.strip().lower()
```

Fallback to keyword matching if Haiku call fails.

### 5.3 Vault File Reading

The brain can read vault files on-demand — not via tools, but via internal logic:

```python
def _read_vault_file(path: str) -> str | None:
    """Read a vault file. Limited to {{VAULT_PATH}}."""
    full = Path(VAULT_PATH) / path
    if not full.exists() or not str(full).startswith(VAULT_PATH):
        return None
    return full.read_text(encoding="utf-8")[:4000]  # max 4k tokens
```

**Trigger:** If the brain's response contains `[[wikilink]]` patterns or references a specific file, inject file content in the next call if needed.

### 5.4 Cost Logging

Every API call is logged:

```python
def _log_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int):
    """Log cost in a structured format."""
    # Prices per 1M tokens (update as pricing changes)
    prices = {
        "<top-tier-model>":  {"input": 15.0, "output": 75.0, "cached": 1.875},
        "<mid-tier-model>":  {"input": 3.0,  "output": 15.0, "cached": 0.375},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0,  "cached": 0.08},
    }
    ...
```

### 5.5 Privacy Middleware (Parry)

Simple version — check the brain's response before sending:

```python
PARRY_CHECKS = [
    # Privacy: never mention L3/L4 content
    lambda text: not any(kw in text.lower() for kw in PRIVACY_KEYWORDS),
    # Configurable content filters
    lambda text: not any(kw in text.lower() for kw in BLOCKED_KEYWORDS),
]
```

If Parry triggers: suppress the response, log, and send a generic reply instead.

---

## 6. Prompt Caching Strategy

Anthropic prompt caching gives 90% discount on cached tokens.

```python
system_prompt = [
    # Block 1: Static personality (cache breakpoint)
    {
        "type": "text",
        "text": PERSONALITY_PROMPT,  # ~3000 tokens
        "cache_control": {"type": "ephemeral"}
    },
    # Block 2: Interface rules + privacy middleware (cache breakpoint)
    {
        "type": "text",
        "text": TELEGRAM_RULES + PARRY_RULES,  # ~800 tokens
        "cache_control": {"type": "ephemeral"}
    },
    # Block 3: Active context (updated every 15 min)
    {
        "type": "text",
        "text": active_context,  # ~2000 tokens
        "cache_control": {"type": "ephemeral"}
    },
]
```

With 5-minute TTL and Telegram polling every 2 seconds, the system prompt stays cached between messages that arrive within 5 minutes.

**Estimated cost per message (Sonnet):**
- System prompt: 6,000 tokens x $0.375/MTok (cached) = **$0.002**
- Input (history + new): ~2,000 tokens x $3/MTok = **$0.006**
- Output: ~200 tokens x $15/MTok = **$0.003**
- **Total: ~$0.01 per message** (vs subprocess which starts an entire Claude session)

---

## 7. Platform Adapters

The Brain class communicates with messaging platforms through a thin adapter layer. See `architecture/platform-adapter-spec.md` for the full specification.

Key points:
- `BasePlatformAdapter` defines `start()`, `stop()`, `heartbeat()`, `receive()`, `send()`, `download_media()`
- `InboundEvent` normalizes all platform messages into a common format
- `OutboundResponse` provides a platform-agnostic response structure
- The core loop iterates over all registered adapters, routing events through the Brain

The Telegram adapter is the first implementation. Signal, Matrix, Discord, and PWA adapters follow as needed.

---

## 8. Dependencies

### New
- `anthropic` — Anthropic Python SDK
- Semantic memory system (e.g., `mempalace` — already installed)

### Existing (unchanged)
- `requests` — Telegram API
- `google-genai` — Gemini TTS + STT + vision
- `ffmpeg` — audio conversion

### Environment Variables
- `ANTHROPIC_API_KEY` — required. Store in `.env` or as system environment variable
- `TELEGRAM_BOT_TOKEN` — {{BOT_TOKEN}}
- `TELEGRAM_USER_ID` — {{TELEGRAM_USER_ID}} (for authorization)

---

## 9. Migration Plan

### Phase 0 — Preparation
- [ ] Anthropic API key provisioned
- [ ] `pip install anthropic` in the bot's environment
- [ ] Verify that the semantic memory system can be imported directly (not just MCP)

### Phase 1 — Brain Class
- [ ] New `Brain` class with `reply(text, sentiment) -> str`
- [ ] System prompt built from vault files (character.md, text.md, voice profile)
- [ ] Prompt caching implemented
- [ ] Conversation history upgraded (dataclass, token budget)
- [ ] `_larry_reply()` wired to `Brain.reply()`
- [ ] Tests: verify responses, correct tonality, no regression

### Phase 2 — Semantic Memory Integration
- [ ] `_memory_search()` with trigger logic
- [ ] KG query per message (entity match)
- [ ] Context injected as user message before new message
- [ ] Tests: verify memory context influences responses

### Phase 3 — Model Selection + Cost Logging
- [ ] `_pick_model()` with heuristic
- [ ] Cost logging per call
- [ ] `/model`, `/cost`, `/context` commands
- [ ] Budget cap (daily/monthly)

### Phase 4 — Privacy + Personalities
- [ ] Parry checks on output
- [ ] `/personality` command
- [ ] Dynamic system prompt based on active personality
- [ ] Vault file reading on-demand

### Phase 5 — Polish
- [ ] Upgraded sentiment analysis (Haiku)
- [ ] `/forget`, `/memory` commands
- [ ] Active-context auto-refresh (every 15 min)
- [ ] Stress tests: 50 messages in sequence, memory usage, token consumption
- [ ] Diary integration: `mempalace_diary_write` at Telegram session end

---

## 10. Risks

| Risk | Likelihood | Consequence | Mitigation |
|------|------------|------------|------------|
| API key missing/expired | Low | No responses | Fallback to `claude -p` |
| Memory search slow | Medium | Slow response time | Timeout 3s, skip if slow |
| Token cost runaway | Low | Expensive | Budget cap + daily log |
| System prompt too large | Medium | Truncation | Measure and limit to 8k tokens |
| Personality files changed | Low | Stale prompt | Reload every 15 min |
| Rate limiting (Anthropic) | Low | 429 errors | Backoff + fallback |
| Memory import conflict | Medium | Crash | Try/except, graceful degradation |

---

## 11. Design Decisions (Parked)

These questions are parked for collaborative design. Grouped:

### PWA Architecture
1. **Repo structure** — Separate repo? Part of main vault repo? Scaffold?
2. **Backend stack** — FastAPI? Flask? Starlette? Or Node (Next.js) with Python subprocess?
3. **Frontend stack** — Vanilla + HTMX? React? Svelte? Vue?
4. **Hosting** — Local dev server? Tailscale for external access? Cloudflare Tunnel?
5. **Auth** — Needed? (LAN-only = maybe not. Tailscale = built-in auth. Tunnel = needed)
6. **Shared session** — Should PWA chat and Telegram share conversation history? Or separate?

### Brain Design
7. **Async or sync?** — `anthropic` SDK supports both. Sync = simpler, async = faster with parallel calls (TTS + response). PWA likely requires async (websocket)
8. **Streaming?** — Should the brain start sending text before the full response is ready? PWA = natural with websocket. Telegram = "typing" indicator
9. **Multi-turn tools?** — Should the brain use tool_use (vault-read, memory-search as tools) instead of pre-injection? More flexible but more expensive
10. **Max response length?** — TTS-friendly = short. But sometimes longer responses needed. Dynamic based on question + interface?

### Memory Integration
11. **Direct import vs MCP?** — Direct import is faster but requires matching Python env. MCP via subprocess/socket is more isolated
12. **Trigger logic** — Which messages trigger memory search? All? Only questions? Heuristic?

### Context & Memory
13. **Active-context caching** — Read the file every 15 minutes, or per message? (~2k tokens)
14. **Session definition** — What defines "a session"? Timeout? Explicit `/forget`? Daily boundary?
15. **Vault file reading** — Should the brain read files proactively, or only when asked?

### Security & Operations
16. **Privacy over Telegram** — L3/L4 content must never be sent via Telegram. How to handle explicit requests?
17. **API key management** — System env var or `.env` file?
18. **Budget cap** — Daily/monthly limit? Warning at threshold? Auto-switch to Haiku at cap?
