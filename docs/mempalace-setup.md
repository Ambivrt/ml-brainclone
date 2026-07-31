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

The default model (MiniLM-L6-v2) only supports English. For non-English vaults, swap the embedding model.

### Recommended: multilingual-e5-large

Higher quality than e5-small — 1024-dim embeddings, XLM-RoBERTa backbone.

```bash
# Download ONNX model
# Place in: D:/mempalace-models/multilingual-e5-large-onnx/
#   - model.onnx (~2.2GB)
#   - tokenizer.json

# Set env variable (or patch embedding.py — see below)
set MEMPALACE_EMBEDDING_MODEL=D:/mempalace-models/multilingual-e5-large-onnx

# Re-mine after model change (embeddings are dimension-incompatible)
rmdir /s /q %USERPROFILE%\.mempalace\palace
mempalace mine {{VAULT_PATH}}
```

### Tested models

| Model | Dim | Size | Swedish | English | Notes |
|-------|-----|------|---------|---------|-------|
| MiniLM-L6-v2 (default) | 384 | ~22MB | Unusable | Excellent | English-only |
| multilingual-e5-small | 384 | ~470MB | Good (0.75-0.81) | Good | Lighter option |
| **multilingual-e5-large** | **1024** | ~2.2GB | **Excellent** | **Excellent** | **Recommended** |

### Required patch: embedding.py

ChromaDB needs a custom embedding function to use e5-large. The default MCP server will produce 384-dim query embeddings (mismatch) without it.

Create `embedding.py` in the mempalace package:

```python
import os, numpy as np
import onnxruntime as ort
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

MODEL_DIR = os.environ.get("MEMPALACE_EMBEDDING_MODEL",
    "D:/mempalace-models/multilingual-e5-large-onnx")

_session = None
_tokenizer = None

def _init():
    global _session, _tokenizer
    if _session is not None:
        return
    from tokenizers import Tokenizer
    _tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
    _tokenizer.enable_padding()
    _tokenizer.enable_truncation(max_length=512)
    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3
    sess_opts.intra_op_num_threads = 4
    _session = ort.InferenceSession(
        os.path.join(MODEL_DIR, "model.onnx"),
        sess_options=sess_opts,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

class E5SmallEmbeddingFunction(EmbeddingFunction[Documents]):
    def __call__(self, input: Documents) -> Embeddings:
        _init()
        texts = [t if t.startswith(("query: ", "passage: ")) else f"passage: {t}"
                 for t in input]
        encoded = _tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        input_names = {inp.name for inp in _session.get_inputs()}
        feed = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        outputs = _session.run(None, feed)
        token_embeddings = outputs[0]
        mask = attention_mask.astype(np.float32)
        mask_exp = np.expand_dims(mask, -1)
        pooled = np.sum(token_embeddings * mask_exp, axis=1) / np.clip(mask_exp.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-9, None)).tolist()

_ef_instance = None

def get_embedding_function():
    global _ef_instance
    if _ef_instance is None:
        _ef_instance = E5SmallEmbeddingFunction()
    return _ef_instance
```

Also patch `palace.py`, `searcher.py`, and `mcp_server.py` to call `get_embedding_function()` when opening collections.

**Critical:** Apply patches to the venv running the MCP server, NOT just the system Python.

### Privacy filtering (patch)

Add `max_privacy` parameter to `search_memories()` in `searcher.py`:

```python
def search_memories(query, palace_path, wing=None, room=None,
                    n_results=5, max_privacy=4):
    # Build where filter
    conditions = []
    if wing: conditions.append({"wing": {"$eq": wing}})
    if room: conditions.append({"room": {"$eq": room}})
    if max_privacy < 4:
        conditions.append({"privacy_level": {"$lte": max_privacy}})
    where = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else {})
    ...
```

Expose in `tool_search()` and the MCP schema in `mcp_server.py`.

### MCP server with custom model

In `.mcp.json` (SSE mode — requires external process):

```json
{
  "mcpServers": {
    "mempalace": {
      "type": "sse",
      "url": "http://127.0.0.1:3001/sse"
    }
  }
}
```

Run: `D:/venv-milla/Scripts/python.exe -m mempalace.mcp_server`

---

## Resource Monitoring (Sysmon)

Monitor CPU, RAM, and GPU during mine runs:

```bash
# Install dependencies (in venv)
pip install psutil pynvml

# Run standalone
python nattskift/milla-sysmon.py --duration 1200 --interval 10

# Run alongside mine (background)
python nattskift/milla-sysmon.py --duration 1200 &
python -m mempalace mine {{VAULT_PATH}}
```

Output: `nattskift/logs/sysmon-YYYY-MM-DD-HHMM.json` with peak CPU/RAM/VRAM and time series.

Reference: typical peaks at ~10.6GB RAM, 1.9GB VRAM idle. Full mine ~20 min on RTX 2080.

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

## Room Routing — How It Works and Pitfalls

The miner assigns each file to a room based on `mempalace.yaml`. Understanding the routing logic is critical — bad config sends 90% of files to `general`.

### Detection Order (priority)

```
1. Folder path match     — file path contains a room name or keyword
2. Filename match        — filename contains a keyword
3. Content keyword score — counts keyword hits in file content, highest score wins
4. Fallback              — "general" room
```

### Room Order Matters

The YAML list is processed top-to-bottom. **First match wins.** This means:

```yaml
# BAD: "larry" in larry-system matches "larry-and-the-fourth" folder paths
rooms:
  - name: larry-system
    keywords: [larry, config]
  - name: latf
    keywords: [latf, fourth]

# GOOD: latf before larry-system, use ml-brainclone instead of larry
rooms:
  - name: latf
    keywords: [latf, fourth, larry-and-the-fourth]
  - name: larry-system
    keywords: [ml-brainclone, config]
```

### Common Routing Traps

| Trap | Example | Fix |
|------|---------|-----|
| **Substring collision** | `person` in team matches `01-personal/` folder | Remove ambiguous keywords, use specific names |
| **Broad keywords** | `son` matches `personal`, `json`, `person` | Use longer, specific keywords |
| **Order-dependent** | Generic room before specific | Put specific rooms earlier in YAML |
| **Path vs content** | Folder `daily/` always wins over content keywords | Leverage path matching intentionally |

### `exclude_dirs` — NOT Supported by Miner

The `exclude_dirs` section in `mempalace.yaml` is **not read by the miner**. It's there for documentation only. To actually exclude directories:

1. Add them to `.gitignore` (miner respects this)
2. Or they must be in the hardcoded `SKIP_DIRS` list in `palace.py`

### Verifying Room Distribution

After mining, check distribution:

```bash
mempalace status
```

If `general` has more than ~5% of total drawers, your keywords need work. A well-tuned config routes 95%+ into specific rooms.

---

## Palace Rebuild — When and How

### When to Rebuild

- After changing embedding model (dimension mismatch = corrupt index)
- After major room routing changes (re-route everything)
- When ChromaDB reports "Error finding id" (HNSW/SQLite out of sync)
- When two mine processes ran simultaneously (duplicate/partial state)

### Rebuild Steps

```bash
# 1. Back up diary entries from WAL if needed
# WAL location: ~/.mempalace/wal/write_log.jsonl
# Diary entries have type: "diary_write" in the JSONL

# 2. Nuke the palace
rmdir /s /q %USERPROFILE%\.mempalace\palace
# Or: rm -rf ~/.mempalace/palace

# 3. Re-mine (use explicit Python path on Windows to avoid wrong interpreter)
python -m mempalace mine {{VAULT_PATH}}

# 4. Replay diary entries from WAL (see replay script below)
# 5. Verify: mempalace status
```

### KG is Safe

The knowledge graph lives in `~/.mempalace/knowledge_graph.sqlite3` — completely separate from ChromaDB. Palace nuke does NOT affect KG.

### WAL Diary Recovery

Diary entries are stored IN ChromaDB, so a palace nuke loses them. The WAL (`write_log.jsonl`) keeps a log. Entry format:

```json
{"timestamp": "...", "type": "diary_write", "data": {"agent_name": "Larry", "aaak_raw": "SESSION:...", "entry_preview": "truncated at 200 chars..."}}
```

Write a replay script that reads the WAL, expands AAAK format, and re-inserts into the fresh palace.

### Avoiding Conflicts

**Never run two mine processes simultaneously.** The `file_already_mined` check uses mtime — if process A mines a file, process B skips it (thinks it's done). Result: partial index.

On Windows, be careful with `start cmd` or background processes — they may invoke a different Python interpreter (e.g., WindowsApps stub vs real Python). Always use the explicit path.

### MCP Singleton Proxy — Preventing HNSW Corruption

**Problem:** Claude Code spawns one MCP server per session. Each creates a `chromadb.PersistentClient` that opens HNSW index files exclusively. Multiple PersistentClients on the same palace = HNSW corruption, leading to "Error finding id" exceptions and partial search results.

**Solution:** Use a singleton proxy pattern. The first process becomes PRIMARY (runs the real mempalace MCP server and listens on a local TCP port). Subsequent processes become SECONDARY (proxy stdin/stdout over TCP to the primary). All ChromaDB access happens in one process.

```python
# mempalace-singleton.py (simplified)
PORT = 18923
LOCK_FILE = os.path.expanduser("~/.mempalace/singleton.lock")

def main():
    existing_pid = read_lock()
    if existing_pid and process_alive(existing_pid):
        # SECONDARY: proxy to primary via TCP
        run_proxy(PORT)
    else:
        # PRIMARY: run real MCP server, listen on TCP
        write_lock(os.getpid())
        run_primary(PORT)
```

Configure in `.mcp.json`:
```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python",
      "args": ["-X", "utf8", "$VAULT/03-projects/ml-brainclone/bus/mempalace-singleton.py"],
      "env": { "MEMPALACE_PALACE_PATH": "$CONFIG/palace" }
    }
  }
}
```

**The secondary needs a timeout.** After `create_connection` the socket blocks forever by default, which is comfortable right up until the primary stops answering -- then every session hangs until whatever outer tool timeout finally fires, and restarting the primary does not help because the session's channel is still bound to the dead process. Track outstanding request IDs in the proxy, answer the client with a JSON-RPC error when one ages out, and drop the connection so the next call reaches a fresh primary. Full pattern with the three correctness details: [daemon-stability.md](daemon-stability.md) pattern #18.

**Run the primary as a supervised daemon, not as a side effect of the first session.** When the primary is whichever session happened to start first, it dies with that session, and its heartbeat belongs to nobody. A headless primary (`--primary-daemon`) owns the port, writes a PID and a heartbeat, and lets the watchdog restart it. That heartbeat must be earned by a real self-probe, not written by a timer -- a primary that accepts TCP and answers nothing is the exact failure this setup produces. See [daemon-stability.md](daemon-stability.md) pattern #17.

**Critical interaction with batch jobs:** The singleton holds ChromaDB's HNSW index open. Nightly batch jobs that need exclusive database access (e.g., `mempalace mine`) must shut the singleton down first. Prefer its control channel: a hard kill skips the HNSW flush and can leave the index diverged from `chroma.sqlite3`, after which vector search silently falls back to keyword matching. See [daemon-stability.md](daemon-stability.md) pattern #9.

```bash
# In batch runner: graceful shutdown first, kill only as fallback
if ! python bus/milla_shutdown.py; then
    SINGLETON_PIDS=$(pgrep -f "mempalace-singleton" 2>/dev/null || true)
    [ -n "$SINGLETON_PIDS" ] && echo "$SINGLETON_PIDS" | xargs kill 2>/dev/null || true
    sleep 2
fi

# Set a maintenance flag so the watchdog does not restart the primary mid-mine
# (two PersistentClients on one palace is the corruption the singleton prevents).
touch "$NOTIF_DIR/milla-maintenance.flag"
timeout 900 python -m mempalace mine "$VAULT"
rm -f "$NOTIF_DIR/milla-maintenance.flag"
```

### Post-Rebuild Verification

After a palace rebuild, verify the new index:

```bash
# Check palace database exists
ls ~/.mempalace/palace/chroma.sqlite3

# Check drawer count and room distribution
mempalace status

# Verify search works
mempalace search "test query"
```

**Target metrics for a well-indexed vault:**
- `general` room should contain <5% of total drawers (good keyword routing)
- Total drawer count should roughly match: (number of markdown files) * (average chunks per file, typically 2-5)
- Search results should return relevant content, not config files or scripts

---

## For Multiple Agents

MemPalace supports **specialist agents** — each agent (Larry, Barry, Harry) can have its own wing and diary in the palace. Configure via `mempalace.yaml` after init.
