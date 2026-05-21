# Warry Setup — Sentiment Sensor

Warry is Larry's emotional barometer. It measures sentiment in text — single messages, conversations, or entire archives — without interpreting or advising. Numbers, trends, graphs. The user owns the insight.

- **Larry** — thinks, plans, orchestrates
- **Barry** — sees (images)
- **Harry** — hears and speaks (audio)
- **Parry** — guards, filters, judges
- **Tarry** — remembers when
- **Farry** — watches and directs (video)
- **Warry** — feels the temperature

---

## What Bert Does

| Domain | Function |
|--------|----------|
| Single message | Score from -1.0 (negative) to +1.0 (positive) with confidence |
| Conversation | Per-sender sentiment averages, monthly breakdown, divergence detection |
| Time period | Trend lines, rolling averages, inflection points |
| Daily snapshot | Score today's notes and messages, append to mood log |
| Proactive alert | Flag sustained negative sentiment to Tarry for check-in |

Bert does not interpret ("you seem upset"), advise ("you should talk to someone"), or judge ("that was harsh"). It delivers numbers. The user decides what they mean.

---

## Architecture

Bert is a **local Python service** — not a daemon, not a skill. It sits between the two: a standalone importable module that any agent can call, with a CLI for direct use.

The model loads lazily on first call (~3 seconds) and stays in VRAM until the process exits. No polling, no timers, no background thread.

```
bert/
├── bert_service.py          # Core: Bert class with score(), batch(), analyze_conversation()
├── bert_cli.py              # CLI: bert score, bert analyze, bert trend, bert daily
├── bert_batch.py            # Batch analysis of archive files (conversations, journals)
└── bert_stream.py           # Real-time analysis (incoming messages, session text)
```

### Data flow

```
Any agent or CLI
        │
        │ import / subprocess
        ▼
bert_service.py
        │
        │ lazy-load on first call
        ▼
XLM-RoBERTa model (GPU, ~1.1 GB VRAM)
        │
        │ score / batch / analyze
        ▼
Returns scores + aggregations
        │
        ├── CLI: printed to terminal
        ├── Larry: used in session context
        ├── Bus: posted as bert-alert / bert-flag
        └── Log: appended to mood-log.jsonl
```

### Why not a daemon?

Bert has no reason to poll. Nothing happens between calls. The model loads on demand and stays warm in VRAM. Larry, Telegram listeners, or the night shift call Bert when they need a score — Bert does the work and goes quiet.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `transformers` | Hugging Face pipeline for XLM-RoBERTa |
| `torch` (CUDA) | GPU inference |
| `numpy` | Score aggregation and statistics |

### Model

**`cardiffnlp/twitter-xlm-roberta-base-sentiment`**

- Multilingual (100+ languages)
- 3-class output: negative / neutral / positive
- Mapped to a continuous -1.0 to +1.0 scale via weighted softmax
- ~500 messages/minute on a mid-range NVIDIA GPU (CUDA)
- ~1.1 GB VRAM footprint

The model downloads automatically on first run via Hugging Face Hub.

---

## Installation

### 1. Install Python dependencies

```bash
pip install transformers torch numpy
```

For CUDA support, install the GPU version of PyTorch matching your CUDA version. See [pytorch.org](https://pytorch.org/get-started/locally/) for the correct command.

### 2. Copy Bert files

Copy the `bert/` directory into your vault:

```
03-projects/bert/
├── bert_service.py
├── bert_cli.py
├── bert_batch.py
└── bert_stream.py
```

### 3. Create data directories

Bert stores its output in a private directory:

```
_private/
├── bert-mood-log.jsonl          # Rolling mood log (one JSON object per line)
└── bert-analyses/               # Full conversation analysis reports
```

These paths are configurable — update them in `bert_cli.py` if your vault layout differs.

### 4. Verify GPU

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Bert falls back to CPU if no GPU is available, but performance drops significantly (~50x slower).

---

## CLI Usage

### Score a single message

```bash
python bert_cli.py score "I feel great about this project"
# Output: ██████████  +0.87  (positive, 92%)

python bert_cli.py score "Everything is broken and I hate it"
# Output: █░░░░░░░░░  -0.81  (negative, 88%)

# JSON output for programmatic use
python bert_cli.py score --json "This is fine"
# Output: {"score": 0.1234, "confidence": 0.6521, "label": "neutral"}

# Read from stdin
echo "Hello world" | python bert_cli.py score -
```

### Analyze a conversation archive

```bash
python bert_cli.py analyze path/to/conversation-archive.md
# Parses the archive, scores every message, writes a full report

# Specify output path
python bert_cli.py analyze path/to/archive.md -o path/to/output-sentiment.md
```

The conversation archive must be a markdown file with this format:

```markdown
## 2026-01-15

**Alice:** Had a great meeting today
**Bob:** Same, the client loved the demo

## 2026-01-16

**Alice:** Something went wrong with the deploy
**Bob:** On it, should be fixed within the hour
```

The generated report includes:

- Per-sender statistics (mean, median, standard deviation)
- Monthly breakdown with visual bars
- Divergence periods (when senders' sentiment significantly differs)
- Inflection points (sharp mood shifts in the rolling average)

### View mood trends

```bash
python bert_cli.py trend path/to/bert-mood-log.jsonl --days 30
# Output: ASCII chart with daily averages over the last 30 days
```

### Daily snapshot

```bash
python bert_cli.py daily
# Scores today's daily note + messages, appends to mood log
```

This is typically called by an automated night shift rather than manually.

---

## Python API

```python
from bert_service import Bert

bert = Bert()  # Lazy-load — model loads on first call

# Single score
score, confidence, label = bert.score("This is wonderful")
# score: 0.91, confidence: 0.95, label: "positive"

# Batch scoring (efficient — uses GPU batching)
results = bert.batch(["Great news", "Terrible day", "Meeting at 3"])
# [(0.88, 0.93, "positive"), (-0.76, 0.85, "negative"), (0.02, 0.71, "neutral")]

# Full conversation analysis
messages = [
    {"date": "2026-01-15", "sender": "Alice", "text": "Great meeting today"},
    {"date": "2026-01-15", "sender": "Bob", "text": "Agreed, went really well"},
    # ...
]
analysis = bert.analyze_conversation(messages)
# analysis.per_sender    — per-person stats
# analysis.per_month     — monthly breakdown
# analysis.inflections   — sharp mood shifts
# analysis.divergences   — periods where senders diverge
# analysis.rolling       — rolling average per sender
```

### Device selection

```python
bert = Bert(device="auto")   # GPU if available, else CPU (default)
bert = Bert(device=0)        # Force GPU 0
bert = Bert(device=-1)       # Force CPU
```

---

## Bus Integration

Bert communicates via the brains-bus (brain name: `bert`).

| Direction | Kind | Payload |
|-----------|------|---------|
| `* -> bert` | `bert-score` | `{text}` — returns `{score, confidence, label}` |
| `* -> bert` | `bert-analyze` | `{file_path}` — returns `{summary}` |
| `bert -> larry` | `bert-alert` | `{entity, score, trend, context}` — sustained negative detected |
| `bert -> parry` | `bert-flag` | Sentiment data for Parry gatekeeper decisions |

```bash
# Request a score via the bus
python 03-projects/ml-brainclone/bus/brains-bus.py post \
    --from larry \
    --to bert \
    --kind bert-score \
    --payload '{"text":"Everything is going well"}'

# Read Bert events
python 03-projects/ml-brainclone/bus/brains-bus.py read --brain bert
```

---

## Integration with Other Agents

| Agent | Bert provides | Bert receives |
|-------|---------------|---------------|
| **Larry** | Session mood context, conversation analysis | Text to score |
| **Barry** | Mood-aware prompt suggestions (future) | Nothing |
| **Harry** | Prosody hints based on text sentiment | Transcribed text to score |
| **Parry** | Tonality checks for gatekeeper decisions | Privacy flags |
| **Milla** | Knowledge graph updates on mood shifts | Historical sentiment from KG |
| **Tarry** | Triggers for proactive check-ins | Timing context |
| **Farry** | Sentiment preservation during translation (future) | Text in any language |

### Milla / Knowledge Graph

Bert writes to the knowledge graph when significant changes occur:

| Trigger | Subject | Predicate | Object |
|---------|---------|-----------|--------|
| Mood trend shift | `User` | `mood_trend_is` | `declining since 2026-04-10` |
| Conversation analyzed | `DM_Archive_Name` | `sentiment_snapshot` | `{date, sender1_avg, sender2_avg}` |
| Inflection detected | `User` | `mood_inflection` | `+0.88 spike 2026-10-29` |

### Telegram

Bot listeners can call Bert on incoming messages:

1. Message arrives (text or transcribed voice)
2. `bert.score(text)` — silent, no output to user
3. Score logged to `bert-mood-log.jsonl`
4. If sustained negative (>3 messages below -0.5): flag in Tarry for check-in

### Parry

Parry can query Bert for gatekeeper decisions:

- Tonality check on outgoing email drafts
- Distinguishing task requests from emotional venting
- Extra caution on high-emotion private content

---

## Data Storage

```
_private/
├── bert-mood-log.jsonl          # Rolling log: {timestamp, source, text_hash, score}
├── bert-analyses/               # Saved conversation analysis reports (markdown)
│   ├── project-alpha-sentiment.md
│   └── ...
└── bert-calibration.json        # Personal threshold overrides (future)
```

All Bert output should be treated as private. The mood log and analyses contain sentiment scores derived from personal communication and are not suitable for public repositories.

### Mood log format

Each line in `bert-mood-log.jsonl` is a JSON object:

```json
{
  "timestamp": "2026-04-22T14:30:00",
  "date": "2026-04-22",
  "source": "daily",
  "score": 0.42,
  "confidence": 0.78,
  "label": "positive",
  "text_preview": "First 80 characters of the scored text..."
}
```

---

## Design Decisions

1. **Measures, never interprets** — scores, trends, graphs. Never "you should" or "they seem."
2. **Local, free, private** — all inference on GPU. No API calls. No data leaves the machine.
3. **Lazy-load** — model loads on first call, not at session init. Multiple sessions can coexist without VRAM conflicts.
4. **Silent by default** — Bert only reports when asked, or on sustained anomaly.
5. **Multilingual out of the box** — XLM-RoBERTa handles 100+ languages natively. No language detection step needed.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `torch.cuda.is_available()` returns False | Reinstall PyTorch with CUDA support for your GPU |
| Model download hangs | Check internet, or pre-download: `huggingface-cli download cardiffnlp/twitter-xlm-roberta-base-sentiment` |
| Out of VRAM | Bert needs ~1.1 GB. Close other GPU workloads or use `device=-1` for CPU fallback |
| Encoding errors on Windows | Bert sets `PYTHONIOENCODING=utf-8` automatically. If issues persist, set it in your environment |
| Empty scores (0.0, 0.0, neutral) | Input was empty or whitespace-only after stripping |

---

## See Also

- [larry-setup.md](larry-setup.md) — Larry (Claude Code) configuration
- [harry-setup.md](harry-setup.md) — Harry audio agent (provides transcribed text for scoring)
- [parry-setup.md](parry-setup.md) — Parry gatekeeper (consumes Bert tonality checks)
- [tarry-setup.md](tarry-setup.md) — Tarry temporal daemon (receives check-in triggers)
- [brains-bus-setup.md](brains-bus-setup.md) — Inter-agent event bus
- [architecture-overview.md](architecture-overview.md) — Agent ecosystem overview
