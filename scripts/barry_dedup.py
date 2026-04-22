"""barry_dedup — prompt-hash deduplication for image generation.

Prevents re-generating identical or near-identical prompts within a
lookback window.  Hash is SHA-256 of a normalised prompt (lowered,
whitespace-collapsed, stop-words stripped).

Designed to work with barry_audit.py — it reads the audit log to build
its cache and can also be updated by the generation pipeline after each
new image.

Usage (standalone):
    python barry_dedup.py --build            # build cache from audit log
    python barry_dedup.py "a fluffy cat"     # check if prompt was used

Usage (library):
    from barry_dedup import check_duplicate, register_prompt

    dupe = check_duplicate("a fluffy cat")
    if dupe:
        print(f"Already generated: {dupe['filename']}")
    else:
        # ... generate ...
        register_prompt("a fluffy cat", "barry-00042.png", "/path/to/file", "chroma")

ENV:
    VAULT_ROOT — vault root (defaults to ~/vault if unset)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", Path.home() / "vault"))
# The audit log is typically in the image-mode project directory
AUDIT_LOG = VAULT_ROOT / "03-projects" / "image-mode" / "audit-log.jsonl"
HASH_CACHE = VAULT_ROOT / "_private" / "image-prompt-hashes.json"
LOOKBACK_DAYS = 30


def _normalize_prompt(prompt: str) -> str:
    """Normalize for consistent hashing across trivial variations."""
    p = prompt.lower().strip()
    p = re.sub(r"\s+", " ", p)
    p = re.sub(r"[,.]", "", p)
    p = re.sub(r"\b(a|an|the|of|in|on|at|to|for|with|and|or)\b", "", p)
    return re.sub(r"\s+", " ", p).strip()


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(_normalize_prompt(prompt).encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if HASH_CACHE.exists():
        try:
            return json.loads(HASH_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    HASH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    HASH_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def build_cache_from_audit() -> dict:
    """Rebuild cache by scanning the audit log for recent generations."""
    cache = {}
    if not AUDIT_LOG.exists():
        return cache
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    with open(AUDIT_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") not in ("api-complete", "pw-complete",
                                           "generation"):
                continue
            ts = entry.get("ts", "")
            if ts < cutoff:
                continue
            prompt = entry.get("prompt", entry.get("description", ""))
            if not prompt:
                continue
            h = _hash_prompt(prompt)
            cache[h] = {
                "ts": ts,
                "filename": entry.get("filename", "?"),
                "filepath": entry.get("filepath", ""),
                "model": entry.get("model", ""),
                "prompt_preview": prompt[:80],
            }
    _save_cache(cache)
    return cache


def check_duplicate(prompt: str, rebuild: bool = False) -> dict | None:
    """Return info about a previous generation with a similar prompt, or None."""
    cache = _load_cache()
    if not cache or rebuild:
        cache = build_cache_from_audit()
    return cache.get(_hash_prompt(prompt))


def register_prompt(prompt: str, filename: str, filepath: str = "",
                    model: str = ""):
    """Record a newly generated prompt in the cache."""
    cache = _load_cache()
    cache[_hash_prompt(prompt)] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "filename": filename,
        "filepath": filepath,
        "model": model,
        "prompt_preview": prompt[:80],
    }
    _save_cache(cache)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--build":
        c = build_cache_from_audit()
        print(f"Cache built: {len(c)} unique prompts "
              f"(last {LOOKBACK_DAYS} days)")
    elif len(sys.argv) > 1:
        d = check_duplicate(" ".join(sys.argv[1:]), rebuild=True)
        if d:
            print(f"DUPLICATE: {d['filename']} ({d['ts']})")
            print(f"  Prompt: {d['prompt_preview']}")
        else:
            print("No duplicate found.")
    else:
        print("Usage: barry_dedup.py --build | barry_dedup.py 'prompt text'")
