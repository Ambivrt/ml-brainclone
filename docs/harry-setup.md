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
  → mood-log (L4) + log_cost()
```
Model: `gemini-live-2.5-flash-native-audio` (GA on Vertex AI).
30 HD voices, barge-in, VAD, affective dialog.
Note: Non-English languages (e.g. Swedish) are forced via system instruction — not officially supported.

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

## Status

- [x] Gemini TTS (harry-tts.py) — live
- [x] Gemini STT + Mood (harry-stt.py) — live
- [x] Gemini Realtime Voice (harry-live.py) — live (Swedish via system instruction)
- [x] Venice music/SFX — available via Playwright
- [x] FFmpeg mixing — live
- [x] Subprocess isolation — voice pipeline in separate process
- [x] Whisper fallback — local GPU fallback when Gemini fails
- [x] Memory profiling — tracemalloc before/after voice processing
- [ ] Larry skills (/listen, /talk) — planned
- [ ] Mood pattern analysis (night shift) — planned
- [ ] Automatic Suno integration — planned
