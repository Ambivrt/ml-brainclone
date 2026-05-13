# Harry Setup — Audio, Speech and Music

Harry is Larry's audio agent. Text-to-speech via Gemini TTS, music generation via Venice, SFX via Venice, mixing via FFmpeg.

---

## Quick Start

```bash
# --- TTS (Text-to-Speech) ---
python 03-projects/harry/harry-tts.py "path/to/file.md" --dry   # Preview segments
python 03-projects/harry/harry-tts.py "path/to/file.md"          # Generate
python 03-projects/harry/harry-tts.py "file.md" --voice Erinome  # Voice override

# --- STT (Speech-to-Text + Mood) ---
python 03-projects/harry/harry-stt.py                # Push-to-talk loop (Ctrl+Shift+L)
python 03-projects/harry/harry-stt.py --once          # Single recording
python 03-projects/harry/harry-stt.py --once --note   # Record → save as vault note
python 03-projects/harry/harry-stt.py --duration 10   # Fixed 10 second recording
python 03-projects/harry/harry-stt.py --json           # Raw JSON output (for piping)

# --- Realtime Voice (Bidirectional) ---
python 03-projects/harry/harry-live.py                # Start conversation (default voice)
python 03-projects/harry/harry-live.py --voice Erinome # Choose voice
python 03-projects/harry/harry-live.py --device 1      # Select microphone
python 03-projects/harry/harry-live.py --transcript-only # Text only, no audio playback

# --- Utilities ---
python 03-projects/harry/harry-stt.py --list-devices   # List microphones
```

---

## Architecture

### TTS (Text-to-Speech)
```
User → Larry → harry-tts.py "file.md"
  → parse_voice_markup() → segment per ::voice[name]
  → Gemini TTS API (Vertex AI, GCP project: {{GCP_PROJECT}})
  → PCM data (24kHz, 16-bit, mono) per segment
  → concat_wav_segments() → combined WAV
  → FFmpeg: atempo (speed adjustment) + libmp3lame → MP3 192kbps
  → Saved to {{AUDIO_PATH}}/01-tts/{file.stem}.mp3
  → log_cost() → cost-log.csv
```

### STT (Speech-to-Text + Mood)
```
Microphone → sounddevice (16kHz PCM) → WAV bytes
  → Gemini 2.5 Flash (audio input + mood prompt)
  → JSON: {transcript, mood: {energy, mood, pace, confidence}}
  → mood-log (L4) + optional vault note (00-inbox/)
  → log_cost()
```

### Realtime Voice (Bidirectional)
```
Microphone → sounddevice (16kHz PCM) → Gemini Live API (WebSocket)
  ← Audio response (24kHz PCM) → sounddevice playback
  ← Text transcripts (both sides) → transcript-log (L4)
  ← Tool calls (blocking FunctionCall) → vault_search / kg_query → response
  → mood-log (L4) + log_cost()
```
Model: `gemini-live-2.5-flash-native-audio` (GA on Vertex AI).
30 HD voices, barge-in, VAD, affective dialog.
Note: Non-English languages (e.g. Swedish) are forced via system instruction — not officially supported.

#### Live Tools (Blocking FunctionCall)

Since `google-genai` 2.1.0, Gemini Live supports blocking function calls. The model pauses audio generation, calls a tool, waits for the result, and continues speaking with the answer. This gives the realtime voice agent access to the same knowledge sources as the text agent.

Tools are defined as `types.FunctionDeclaration` and passed via `LiveConnectConfig(tools=...)`. The receive loop checks `response.tool_call` before `response.server_content`:

```python
LIVE_TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="vault_search",
            description="Search the vault for relevant notes.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Search query"),
                },
                required=["query"],
            ),
        ),
    ])
]

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    tools=LIVE_TOOLS,
    # ... other config
)

# In the receive loop:
async for response in session.receive():
    tc = response.tool_call
    if tc:
        for fc in tc.function_calls:
            result = await asyncio.get_event_loop().run_in_executor(
                None, tool_handler, fc.args.get("query", ""))
            await session.send_tool_response(
                function_responses=[types.FunctionResponse(
                    name=fc.name, id=fc.id,
                    response={"result": result[:4000]},
                )]
            )
        continue
    # ... handle audio/text as before
```

Tool execution runs in a thread executor to avoid blocking the async event loop. Keep tool timeouts short (5-8s) -- the user is waiting in a live conversation.

---

## Voice Markup

Harry reads markdown files with `::voice[name]` markup:

```markdown
::voice[narrator]
The narrator describes the scene.

::voice[main]
The main character speaks.

::voice[female]
The female character responds.
```

Text without markup is treated as narrator voice.
Frontmatter and markdown headers (`#`) are removed automatically.

---

## Voice Library (Gemini TTS)

Define your own voice map in `harry-tts.py`. Example configuration:

```python
VOICE_MAP = {
    # Male voices
    "main":       "Iapetus",    # Deep, intimate
    "other_male": "Enceladus",  # Dark, calm
    "alt_male":   "Sadaltager", # Calm, low

    # Female voices
    "female":     "Erinome",    # Soft, warm — narrator favorite
    "young_f":    "Zephyr",     # Light, youthful
    "alt_female": "Aoede",      # Warm

    # Narrator
    "narrator":   "Erinome",    # Soft, warm
    "berattare":  "Erinome",
}

DEFAULT_VOICE = "Iapetus"
DEFAULT_SPEED = 1.2
```

**Recommendation:** Test all available Gemini TTS voices and pick 3-5 that work well for your use case.

---

## TTS Model Configuration

```python
TTS_MODEL = "gemini-2.5-pro-preview-tts"   # Pro: higher expressivity, nuanced emotion
GCP_PROJECT = "{{GCP_PROJECT}}"
GCP_LOCATION = "us-central1"
```

Authentication: `google-auth` Application Default Credentials (Vertex AI).

**Setup:**
```bash
gcloud auth application-default login
gcloud config set project {{GCP_PROJECT}}
```

---

## FFmpeg

Install FFmpeg and set the path in `harry-tts.py`:

```python
ffmpeg = "ffmpeg"  # or full path, e.g. "/usr/bin/ffmpeg"
```

Used for:
- Speed adjustment (`atempo`)
- WAV → MP3 conversion (libmp3lame, 192kbps)
- Mixing: panning, reverb (aecho), volume levels

---

## File Structure

```
{{AUDIO_PATH}}/
├── 01-tts/       ← Text-to-speech output
├── music/        ← Generated music (Venice MiniMax/ACE-Step)
├── sfx/          ← Sound effects (Venice MMAudio v2)
└── .trash/       ← Trash (30-day retention)
```

---

## Music (Venice)

| Type | Model | Cost | Control |
|------|-------|------|---------|
| Music | MiniMax v2 | ~$0.03/gen | Style, tempo, instruments |
| Music | ACE-Step | ~$0.04/gen | Advanced composition |
| SFX | MMAudio v2 | ~$0.01/gen | Environmental sounds, short duration |

---

## TTS Style Guidelines

- Minimal prosody tweaking — write like a radio drama script, not prose
- Natural pause cues through sentence structure
- Each `::voice[name]` block = one segment = one API call → concatenated
- Keep segments reasonably short for natural-sounding output

---

## Backup

| Layer | Source | Destination | Frequency |
|-------|--------|-------------|-----------|
| NAS | `{{AUDIO_PATH}}/` | `{{NAS_PATH}}/audio` | Every 6h (robocopy /MIR) |

---

## Cost Logging

```python
log_cost(file_stem, TTS_MODEL, "audio", privacy_level, "harry",
         total_chars, "characters", 0.0)
```

Gemini TTS Vertex AI is free/token-based — `cost_usd` logged as 0.0.

---

## Dependencies

```bash
pip install sounddevice numpy keyboard google-genai
```

- `sounddevice` + `numpy` — microphone capture and audio playback (no C++ build tools needed)
- `keyboard` — hotkey detection (push-to-talk)
- `google-genai` — Gemini API (TTS, STT, Live)
- `ffmpeg` — audio conversion/mixing (system install)

## Subprocess Isolation (Telegram Voice)

When handling voice messages via Telegram, the transcription pipeline runs in an isolated `multiprocessing.Process` to prevent crashes from taking down the listener:

```
Listener (parent)
  │
  ├── Download audio file
  ├── Spawn worker process ──► _voice_pipeline_worker()
  │     ├── Gemini STT (with retry)
  │     ├── Whisper fallback (if Gemini fails)
  │     └── Create vault note
  │     └── Return results via Queue
  ├── Wait (60s timeout)
  │     └── On timeout: worker.kill() + error message
  ├── Send reply, TTS, queue update (parent-only)
  └── Log memory delta (tracemalloc)
```

### Whisper Fallback

If Gemini STT fails all retries, the worker attempts local transcription via `faster-whisper` (GPU-accelerated):

```python
# Uses faster-whisper with CUDA
# Model: medium, language: forced to your locale
# Result tagged "whisper-fallback" for traceability
```

Install: `pip install faster-whisper`

---

## Music Generation (Lyria — Vertex AI)

Lyria is Google's music generation model family, available through Vertex AI. It gives Harry the ability to generate instrumental clips and full songs with vocals via API — no browser, no web pipeline.

### Model Variants

| Model | ID | Status | Max Length | Vocals | Price |
|-------|-----|--------|------------|--------|-------|
| Lyria 2 | `lyria-002` | **GA** | 30s instrumental | No | $0.06 / 30s clip |
| Lyria 3 Clip | `lyria-3-clip-preview` | Preview | 30s | Yes | $0.04 / 30s clip |
| Lyria 3 Pro | `lyria-3-pro-preview` | Preview | ~3 min | Yes | $0.08 / song |
| Lyria RealTime | (Gemini API, not Vertex) | Experimental | Streaming | Instrumental | Free during preview |

**Default:** `lyria-002` — cheapest, most stable, GA. Use Lyria 3 Pro when vocals/lyrics are needed.

**Lyria RealTime:** Separate stack (Gemini API + AI Studio). Treat as its own integration if streaming music becomes relevant.

### API Architecture

Lyria 2 and Lyria 3 use different endpoint patterns:

| Component | Lyria 2 | Lyria 3 (Pro/Clip) |
|-----------|---------|---------------------|
| API version | `v1` | `v1beta1` |
| Location | `us-central1` (or other region) | `global` only |
| Host | `{location}-aiplatform.googleapis.com` | `aiplatform.googleapis.com` (no region prefix) |
| Path suffix | `publishers/google/models/{model}:predict` | `interactions` (no publisher, no :predict) |
| Output | Base64 WAV in `predictions[]` | Base64 MP3 + lyrics + structure in `outputs[]` |

**Common pitfall:** Calling Lyria 3 via the Lyria 2 endpoint returns `404 NOT_FOUND` with a misleading "your project does not have access" message. It is a routing error, not an access block.

### Setup

```bash
# 1. Enable Vertex AI API in your GCP project
gcloud services enable aiplatform.googleapis.com

# 2. Authenticate
gcloud auth application-default login
gcloud config set project {{GCP_PROJECT}}

# 3. Install dependencies
pip install google-auth requests
```

Authentication: Application Default Credentials (same as Gemini TTS).

### Capabilities and Limits

- **Lyria 2:** 48 kHz stereo WAV, ~30s per clip. Prompt in US English. Supports `negative_prompt` and `seed`/`sample_count` (max 4). Instrumental only.
- **Lyria 3 Pro:** Up to ~3 min. Supports user-specified lyrics. Multimodal input (text + reference image). Languages: EN, DE, ES, FR, HI, JA, KO, PT.
- **All variants:** No streaming on Vertex (RealTime is separate). SynthID watermark embedded. Default quota: 10 requests/min per model. Content safety filters apply.

### Relationship to Venice Music

Venice (MiniMax/ACE-Step) remains available for music generation via Playwright. Lyria is the API-based alternative — faster for automated pipelines (Telegram bot delivery, scheduled generation) where browser automation is not ideal.

---

## Status

- [x] Gemini TTS (harry-tts.py) — live
- [x] Gemini STT + Mood (harry-stt.py) — live
- [x] Gemini Realtime Voice (harry-live.py) — live (Swedish via system instruction)
- [x] Venice music/SFX — available via Playwright
- [x] FFmpeg mixing — live
- [x] Subprocess isolation — voice pipeline in separate process
- [x] Whisper fallback — local GPU fallback when Gemini fails
- [x] Memory profiling — tracemalloc before/after voice processing
- [x] Lyria 2 (instrumental) — live via Vertex AI
- [x] Lyria 3 Pro (vocals/lyrics) — live via Vertex AI
- [x] Lyria 3 Clip (short jingles/intros) — live via Vertex AI
- [x] Lyria bot trigger (`/musik` command) — live
- [x] Gemini Live blocking tools (vault_search, kg_query) — live
- [ ] Larry skills (/listen, /talk) — planned
- [ ] Mood pattern analysis (night shift) — planned
- [ ] Automatic Suno integration — planned
