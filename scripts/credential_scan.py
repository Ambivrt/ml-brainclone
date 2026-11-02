"""credential_scan.py -- the central pattern list for secrets, no dependencies.

Everything that looks for keys in text imports this: the dispatch gate that
checks content before it leaves the machine, the memory layer (to wash every
write), and the privacy guard hook (to block keys in writes to the vault).
The module only imports re, so hooks and long-running services can load it
cheaply.

    scan(text)   -> ["github-pat", ...]   rule ids that matched, never the key itself
    redact(text) -> (washed text, rule ids)

Borrowed from Hermes Agent 0.22 (memory handoffs are washed before they
reach a memory layer), tightened with a placeholder filter:
`API_KEY=$env:FOO` and `TOKEN: <your key>` in a doc are references, not keys.

All patterns are public, generic key formats. Add your own provider formats
to SECRET_PATTERNS.
"""
from __future__ import annotations

import re

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic-api-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")),
    ("openai-api-key", re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("github-pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("github-fine-grained-pat", re.compile(r"github_pat_[A-Za-z0-9_]{60,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("pem-private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9_\-\.=]{24,}")),
    ("env-secret-assignment", re.compile(
        r"(?im)^\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY)"
        r"[A-Z0-9_]*\s*[=:]\s*(\S{8,})")),
]

# Values that point at a key instead of being one. Applies to the env rule
# only: the other patterns have prefixes and lengths that placeholders do not reach.
_PLACEHOLDER = re.compile(
    r"""^["'`]?(?:\$|%|<|\{|\[|\(|os\.environ|os\.getenv|process\.env|getenv|env:|secrets?[./:]"""
    r"""|your|xxx|\.\.\.|\*{3}|changeme|placeholder|redacted|none\b|null\b|true\b|false\b)""",
    re.IGNORECASE,
)

ENV_RULE = "env-secret-assignment"


def _real_env_hits(pattern: re.Pattern, text: str) -> list[re.Match]:
    return [m for m in pattern.finditer(text) if not _PLACEHOLDER.match(m.group(1))]


def scan(text: str) -> list[str]:
    """Rule ids that match the text, in pattern order, without duplicates."""
    if not text:
        return []
    hits: list[str] = []
    for rule_id, pattern in SECRET_PATTERNS:
        found = _real_env_hits(pattern, text) if rule_id == ENV_RULE else pattern.search(text)
        if found:
            hits.append(rule_id)
    return hits


def redact(text: str) -> tuple[str, list[str]]:
    """Replaces every key with [REDACTED:<rule>]. The env rule keeps the
    name and washes only the value, so the line is readable afterwards."""
    if not text:
        return text, []
    hits: list[str] = []
    for rule_id, pattern in SECRET_PATTERNS:
        if rule_id == ENV_RULE:
            matches = _real_env_hits(pattern, text)
            for m in reversed(matches):
                text = text[:m.start(1)] + f"[REDACTED:{rule_id}]" + text[m.end(1):]
            if matches:
                hits.append(rule_id)
            continue
        text, n = pattern.subn(f"[REDACTED:{rule_id}]", text)
        if n:
            hits.append(rule_id)
    return text, hits
