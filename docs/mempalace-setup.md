# MemPalace — Semantic Memory for Larry

MemPalace gives your AI second brain a **semantic, searchable memory layer**. Instead of text-matching files with grep, your AI agent can search by *meaning* — "why did we change the auth flow?" finds relevant context even if those exact words never appear.

**Source:** [github.com/milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace) (MIT license)

---

## What It Adds

| Capability | Without MemPalace | With MemPalace |
|------------|-------------------|----------------|
| **Search** | Grep/Glob (exact text match) | Semantic search (meaning-based) |
| **Context loading** | Manual file reads | Compressed wake-up summary (~600 tokens) |
| **Memory size** | Limited by context window | 19,000+ indexed knowledge chunks |
| **Cost** | — | Zero. Fully local, no API calls |
| **Integration** | — | MCP server (19 tools) in Claude Code |

---

## How It Works

```
Vault (markdown files)
    ↓
mempalace mine     → chunks files, generates embeddings (multilingual-e5-small, ONNX, CUDA GPU)
    ↓
ChromaDB           → local vector database (SQLite-backed)
    ↓
mempalace search   → semantic similarity search
mempalace wake-up  → compressed context for session start
mempalace compress → AAAK Dialect (~30x compression)
    ↓
MCP Server         → 19 tools available directly in Claude Code
```

---

## Installation

### 1. Install MemPalace

```bash
pip install mempalace
```

### 2. GPU Acceleration (Recommended)

MemPalace uses ONNX Runtime for embeddings. GPU acceleration significantly speeds up mining.

```bash
# Install GPU runtime (replaces CPU version)
pip install onnxruntime-gpu

# Install CUDA 12 runtime DLLs via pip
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-cuda-runtime-cu12
```

**Windows DLL setup** — ONNX Runtime needs CUDA DLLs in the system PATH. The pip packages install DLLs under `site-packages/nvidia/*/bin/` but ONNX can't find them there. Fix:

```bash
# Create a central DLL directory
mkdir C:\cuda-libs

# Copy all CUDA DLLs there
copy site-packages\nvidia\cublas\bin\*.dll C:\cuda-libs\
copy site-packages\nvidia\cudnn\bin\*.dll C:\cuda-libs\
copy site-packages\nvidia\cufft\bin\*.dll C:\cuda-libs\
copy site-packages\nvidia\cuda_runtime\bin\*.dll C:\cuda-libs\

# Add C:\cuda-libs to your Windows user PATH (permanent)
# System Settings → Environment Variables → Path → New → C:\cuda-libs
```

**Verify GPU is active:**
```python
import onnxruntime as ort
print(ort.get_available_providers())
# Should include: 'CUDAExecutionProvider'
```

**Requirements:** NVIDIA GPU (any CUDA-capable), driver supporting CUDA 12+. The pip packages handle everything else — no separate CUDA Toolkit installer needed.

### 3. Initialize and Mine

```bash
# Detect structure
mempalace init {{VAULT_PATH}} --yes

# Index all files
mempalace mine {{VAULT_PATH}}

# Test search
mempalace search "your query here"
```

### 4. Configure Identity

Create `~/.mempalace/identity.txt` with a short description of who you are. This appears in wake-up context.

### 5. Add MCP Server to Claude Code

```bash
claude mcp add mempalace -- python /path/to/site-packages/mempalace/mcp_server.py
```

This gives Claude Code 19 tools for reading and writing palace data:
- `mempalace_search` — semantic search with optional wing/room filter
- `mempalace_status` — drawer counts, wing/room breakdown
- `mempalace_list_wings` / `mempalace_list_rooms` — palace structure
- `mempalace_add_drawer` — file new content
- `mempalace_delete_drawer` — remove by ID
- And more (taxonomy, duplicate check, graph traversal)

### 6. Compress (Optional)

```bash
mempalace compress --wing <wing_name>
```

AAAK Dialect compresses context ~30x, enabling much richer wake-up summaries.

---

## Daily Usage

```bash
# Search for anything
mempalace search "what was the decision on pricing"

# Get session wake-up context
mempalace wake-up

# Re-mine after vault changes
mempalace mine {{VAULT_PATH}}

# Check what's indexed
mempalace status
```

---

## Known Issues

### ChromaDB SQLite Variable Limit

With large vaults (>10,000 chunks), ChromaDB's SQLite backend crashes on unbounded queries:

```
Error: too many SQL variables
```

**Fix:** Patch `layers.py` and `cli.py` in the mempalace package to batch queries:

```python
# Replace: results = col.get(**kwargs)
# With batched version:
docs, metas, ids = [], [], []
batch_size = 5000
offset = 0
while True:
    batch = col.get(**kwargs, limit=batch_size, offset=offset)
    batch_docs = batch.get("documents", [])
    if not batch_docs:
        break
    docs.extend(batch_docs)
    metas.extend(batch.get("metadatas", []))
    ids.extend(batch.get("ids", []))
    if len(batch_docs) < batch_size:
        break
    offset += batch_size
```

This affects `cmd_compress()` in `cli.py` and `L1Layer.generate()` in `layers.py`.

### Compress OOM on Large Vaults

With 20,000+ drawers, `cmd_compress()` accumulates all compressed entries in a list before writing — causing 900MB+ memory usage and potential crashes.

**Fix:** Patch `cmd_compress()` in `cli.py` to stream-process: compress each drawer and upsert in batches of 500, instead of holding everything in memory:

```python
# Instead of: compressed_entries.append((doc_id, compressed, meta, stats))
# Stream-process: compress + upsert in batches
UPSERT_BATCH_SIZE = 500
upsert_batch_ids, upsert_batch_docs, upsert_batch_metas = [], [], []

for i, (doc, meta, doc_id) in enumerate(zip(docs, metas, ids)):
    compressed = dialect.compress(doc, metadata=meta)
    stats = dialect.compression_stats(doc, compressed)
    # ... accumulate stats ...
    
    upsert_batch_ids.append(doc_id)
    upsert_batch_docs.append(compressed)
    upsert_batch_metas.append(comp_meta)
    
    if len(upsert_batch_ids) >= UPSERT_BATCH_SIZE:
        comp_col.upsert(ids=upsert_batch_ids, documents=upsert_batch_docs,
                        metadatas=upsert_batch_metas)
        upsert_batch_ids, upsert_batch_docs, upsert_batch_metas = [], [], []
    
    if (i + 1) % 5000 == 0:
        print(f"  Progress: {i + 1}/{total_count}")

# Flush remaining
if upsert_batch_ids:
    comp_col.upsert(ids=upsert_batch_ids, ...)
```

### Wake-up Quality (L1 Layer)

With large vaults, the L1 wake-up layer shows config files and scripts instead of actual content, because all drawers have the same default importance score (3).

**Fix:** Patch `Layer1.generate()` in `layers.py` with two improvements:

1. **File-type scoring** — boost markdown content, penalize scripts/config:
```python
sl = source.lower().replace('\\', '/')
if sl.endswith(('.py', '.js', '.ts', '.sh')):
    importance *= 0.3       # penalize code
elif sl.endswith(('.json', '.yaml', '.yml')):
    importance *= 0.2       # penalize config
elif sl.endswith('.md'):
    importance *= 1.5       # boost content
# Boost content directories
for d in ('01-personal/', '02-work/', '03-projects/', '04-knowledge/'):
    if d in sl:
        importance *= 2.0
        break
```

2. **Source diversification** — max 2 drawers per source file:
```python
file_counts = defaultdict(int)
MAX_PER_FILE = 2
for imp, meta, doc in scored:
    source = meta.get("source_file", "unknown")
    if file_counts[source] < MAX_PER_FILE:
        top.append((imp, meta, doc))
        file_counts[source] += 1
    if len(top) >= self.MAX_DRAWERS:
        break
```

### TensorRT Warnings

If you don't have TensorRT installed, ONNX Runtime logs fallback warnings. These are harmless — it falls back to CUDA, which is what you want.

### CUDA PATH in Background Processes

On Windows, background processes (e.g. spawned by Claude Code's `run_in_background`) may not inherit the updated user PATH. If CUDA DLLs aren't found, set the PATH explicitly before the command:

```bash
export PATH="/c/cuda-libs:$PATH" && python -c "from mempalace.cli import ..."
```

### Windows Encoding

MemPalace uses Unicode characters (●○) in CLI output. On Windows with cp1252 encoding, wrap calls with UTF-8:

```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
```

---

## Architecture Integration

MemPalace complements the existing memory system (file-based `MEMORY.md` index):

| Layer | Purpose | Technology |
|-------|---------|------------|
| **MEMORY.md** | Curated, structured memories (user prefs, feedback, project state) | Markdown files |
| **MemPalace** | Semantic retrieval over entire vault | ChromaDB + ONNX embeddings |
| **load-context.sh** | Session init (reads key files) | Shell hook |
| **mempalace wake-up** | Compressed vault context | AAAK Dialect |

They work together: MEMORY.md for precise, curated knowledge; MemPalace for broad semantic search when you don't know which file has what you need.

---

## Multilingual Support (Swedish, etc.)

The default model (MiniLM-L6-v2) only supports English. For non-English vaults, swap the embedding model:

### Recommended: multilingual-e5-small

```bash
# Download ONNX model
# Place in: D:/mempalace-models/multilingual-e5-small-onnx/
#   - model.onnx (~470MB)
#   - tokenizer.json (~17MB)
#   - config.json, special_tokens_map.json, tokenizer_config.json

# Set env variable (or patch embedding.py)
set MEMPALACE_EMBEDDING_MODEL=D:/mempalace-models/multilingual-e5-small-onnx

# Re-mine (delete old palace first — embeddings are incompatible)
rmdir /s /q %USERPROFILE%\.mempalace\palace
mempalace mine {{VAULT_PATH}}
```

### Tested models

| Model | Size | Swedish | English | Notes |
|-------|------|---------|---------|-------|
| MiniLM-L6-v2 (default) | ~22MB | Unusable | Excellent | English-only |
| paraphrase-multilingual-MiniLM-L12-v2 | ~471MB | Untested (OOM) | — | OOM on 32GB system |
| **multilingual-e5-small** | ~470MB | **Excellent** (0.75-0.81) | Excellent (0.73) | Recommended |

### MCP server with custom model

In `.mcp.json`:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python",
      "args": ["-m", "mempalace", "mcp"],
      "env": {
        "MEMPALACE_EMBEDDING_MODEL": "D:/mempalace-models/multilingual-e5-small-onnx"
      }
    }
  }
}
```

---

## Agent Integration

All four agents in the Larry ecosystem are integrated with MemPalace:

| Agent | Integration | How |
|-------|-----------|-----|
| **Larry** | MCP server (19 tools) + CLAUDE.md instructions | Semantic search before grep for open-ended queries |
| **Barry** | Pre-generation search + post-generation indexing | `barry.py` searches for similar past prompts, indexes metadata after generation |
| **Harry** | STT transcript indexing | `harry-stt.py` indexes voice notes in Milla after transcription |
| **Parry** | Semantic privacy scanning | `parry.py scan` uses Milla to find private context in public files |

All integrations are graceful — 10s timeout, silent fallback if Milla is unavailable.

---

## For Multiple Agents

MemPalace supports **specialist agents** — each agent (Larry, Barry, Harry) can have its own wing and diary in the palace. Configure via `mempalace.yaml` after init.
