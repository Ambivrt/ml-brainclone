# Telegram v2 — Technical Spec

> Replace `claude -p` subprocess with Anthropic SDK directly in the listener.
> The bot stops cosplaying — and becomes the real brain.
> **Part of the PWA** — the Telegram bot becomes a backend module, not a standalone daemon.

**Status:** Parked — design phase (decisions first, implementation later)

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
│  │ Text-vy  │  │ Image-vy │  │ Audio-vy │  (frontend)  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│  ┌────┴──────────────┴──────────────┴────┐              │
│  │            API layer (FastAPI?)       │              │
│  └────┬──────────────┬──────────────┬────┘              │
│       │              │              │                    │
│  ┌────┴─────┐  ┌─────┴────┐  ┌─────┴────┐              │
│  │  Brain   │  │  Image   │  │  Audio   │  (backends)  │
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

**Key insight:** The `Brain` class is interface-agnostic. Telegram, the PWA chat, and (potentially) CLI all talk to the same brain. The Telegram listener becomes a thin adapter — all intelligence lives in `Brain`.

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
│       │     ├── KG-query (entity context)           │
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
| Default text conversation | Sonnet | Fast, cheap, good enough |
| Complex question (long, references context) | Sonnet | Sufficient |
| Creative / emotional / deep | Opus | Depth needed |
| Simple ack / short reply | Haiku | Fastest, cheapest |

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

MAX_HISTORY = 30
MAX_CONTEXT_TOKENS = 4000  # truncate oldest first when exceeded
```

---

## 4. Existing Features — What Stays

Everything that works today is preserved unchanged:

| Feature | Status |
|---------|--------|
| Telegram long-polling | Unchanged |
| PID file lock | Unchanged |
| Watchdog + exponential backoff | Unchanged |
| Heartbeat file | Unchanged |
| All `/commands` | Extended with new ones |
| `/voice` toggle | Unchanged |
| Gemini TTS | Unchanged |
| Sentiment-based prosody | Upgraded |
| Photo reception + Gemini vision | Unchanged |
| Voice reception + Gemini STT | Unchanged |
| Daily Telegram log | Unchanged |
| notify-queue.json | Unchanged |
| Callback handling | Unchanged |
| Health check daemon | Unchanged |
| larry_notify.py | Unchanged |

---

## 5. New Features

### 5.1 New Commands

| Command | Function |
|---------|---------|
| `/model` | Show/switch active model |
| `/context` | Show current state: personality, history length, last memory search |
| `/forget` | Clear conversation history |
| `/memory <query>` | Explicit semantic memory search |
| `/personality <name>` | Switch personality via Telegram |
| `/cost` | Show approximate session cost |

### 5.2 Sentiment Analysis — Upgrade

Current: keyword matching. New: use Haiku for sentiment classification (~$0.001/call) with keyword fallback.

### 5.3 Vault File Reading

The brain can read vault files on-demand (limited to vault directory, max 4k tokens per file).

### 5.4 Cost Logging

Every API call logged with model, input/output tokens, cached tokens, and calculated cost.

### 5.5 Privacy Middleware

Simple output checks before sending — suppress replies that leak private content, flag and log.

---

## 6. Prompt Caching Strategy

Anthropic prompt caching gives 90% discount on cached tokens.

**Estimated cost per message (Sonnet):**
- System prompt: 6,000 tokens × cached price = ~$0.002
- Input (history + new): ~2,000 tokens = ~$0.006
- Output: ~200 tokens = ~$0.003
- **Total: ~$0.01 per message**

---

## 7. Dependencies

### New
- `anthropic` — Anthropic Python SDK
- Semantic memory system (already installed)

### Existing (unchanged)
- `requests` — Telegram API
- `google-genai` — Gemini TTS + STT + vision
- `ffmpeg` — audio conversion

---

## 8. Migration Plan

| Phase | Scope |
|-------|-------|
| **0 — Prep** | API key, pip install, verify memory system can be imported directly |
| **1 — Brain class** | New `Brain` class with `reply(text, sentiment) → str`. System prompt from vault files. Prompt caching. Upgraded history. Wire into existing `_larry_reply()` |
| **2 — Memory** | Semantic search with trigger logic. KG query per message. Context injection |
| **3 — Model selection + cost** | Model picker heuristic. Cost logging. New commands |
| **4 — Privacy + personalities** | Output checks. `/personality` command. Dynamic system prompt |
| **5 — Polish** | LLM-based sentiment. `/forget`, `/memory`. Active-context auto-refresh. Stress tests |

---

## 9. Design Decisions (Parked)

### PWA Architecture
1. **Repo structure** — Separate repo? Part of main vault repo? Scaffold?
2. **Backend stack** — FastAPI? Flask? Node?
3. **Frontend stack** — Vanilla + HTMX? React? Svelte?
4. **Hosting** — Local dev server? Tailscale? Cloudflare Tunnel?
5. **Auth** — Needed? (LAN-only = maybe not. Tunnel = yes)
6. **Shared session** — Should PWA chat and Telegram share conversation history?

### Brain Design
7. **Async or sync?** — SDK supports both. PWA likely requires async (websocket)
8. **Streaming?** — PWA = natural with websocket. Telegram = "typing" indicator
9. **Multi-turn tools?** — Tool use (vault-read, memory-search as tools) vs pre-injection? More flexible but more expensive
10. **Max response length?** — TTS-friendly = short. But sometimes longer responses needed

### Memory Integration
11. **Direct import vs MCP?** — Direct = faster but tighter coupling. MCP = isolated
12. **Trigger logic** — Which messages trigger memory search?

### Context & Memory
13. **Active-context caching** — Read every 15 min or per message?
14. **Session definition** — What defines a "session"? Timeout? Explicit `/forget`? Daily boundary?
15. **Vault file reading** — Proactive or only on request?

### Security & Operations
16. **Privacy over Telegram** — L3/L4 content must never be sent. Handle explicit requests?
17. **API key management** — Env var or `.env` file?
18. **Budget cap** — Daily/monthly limit? Auto-switch to Haiku at cap?
