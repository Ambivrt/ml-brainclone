"""task_lib — filesystem-primary task model for inter-agent dispatch.

Primary storage: files on disk. 00-inbox/ for pending tasks,
_tasks/{agent}/{processing,done,failed}/ for lifecycle.

The bus is used only for notifying the user when a task completes/fails.
Filesystem is the source of truth — survives DB corruption and restarts.

File format: markdown with YAML frontmatter.
Filename: task-{agent}-{ts}-{slug}-{uuid}.md

Configure the vault root via the VAULT_ROOT environment variable, or pass
it explicitly to the helpers below. The default expands to ~/vault.
"""
from __future__ import annotations

import os
import re
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional


def _vault_root() -> Path:
    root = os.environ.get("VAULT_ROOT")
    if root:
        return Path(root)
    return Path.home() / "vault"


AgentName = Literal["larry", "harry", "barry", "parry"]
VALID_AGENTS = ("larry", "harry", "barry", "parry")


def _inbox() -> Path:
    return _vault_root() / "00-inbox"


def _tasks_root() -> Path:
    return _vault_root() / "_tasks"


def _slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "task"


def _agent_dir(agent: str, bucket: str) -> Path:
    d = _tasks_root() / agent / bucket
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].strip()
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    body = text[end + 4:].lstrip("\n")
    return meta, body


def _append_frontmatter_field(text: str, key: str, value: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    fm = text[3:end]
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(fm):
        fm = pattern.sub(f"{key}: {value}", fm)
    else:
        fm = fm.rstrip() + f"\n{key}: {value}"
    if not fm.endswith("\n"):
        fm += "\n"
    return "---" + fm + "---" + text[end + 4:]


def create_task(
    agent: AgentName,
    title: str,
    description: str,
    *,
    from_source: str = "manual",
    priority: str = "normal",
    context: Optional[dict] = None,
) -> Path:
    """Create a new pending task file in 00-inbox/."""
    if agent not in VALID_AGENTS:
        raise ValueError(f"Invalid agent: {agent}. Choose one of {VALID_AGENTS}")

    task_id = uuid.uuid4().hex[:8]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(title)
    fname = f"task-{agent}-{ts}-{slug}-{task_id}.md"
    inbox = _inbox()
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / fname

    ctx_block = ""
    if context:
        ctx_block = "\n## Context\n```json\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n```\n"

    content = (
        f"---\n"
        f"tags: [task, agent/{agent}]\n"
        f"task_id: {task_id}\n"
        f"agent: {agent}\n"
        f"status: pending\n"
        f"priority: {priority}\n"
        f"from_source: {from_source}\n"
        f"created: {datetime.now().isoformat(timespec='seconds')}\n"
        f"privacy: 2\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"## Description\n{description}\n"
        f"{ctx_block}"
    )
    path.write_text(content, encoding="utf-8")
    return path


def list_pending_for_agent(agent: AgentName) -> list[Path]:
    inbox = _inbox()
    if not inbox.exists():
        return []
    out: list[Path] = []
    for p in inbox.glob(f"task-{agent}-*.md"):
        try:
            meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("agent") == agent and meta.get("status", "pending") == "pending":
            out.append(p)
    out.sort(key=lambda p: p.stat().st_mtime)
    return out


def claim_task(path: Path, agent: AgentName) -> Optional[Path]:
    """Atomic claim: rename to processing/. Returns new path or None if lost race."""
    if not path.exists():
        return None
    dest = _agent_dir(agent, "processing") / path.name
    try:
        os.replace(path, dest)
    except (FileNotFoundError, OSError):
        return None
    try:
        text = dest.read_text(encoding="utf-8")
        text = re.sub(r"^status:\s*pending\s*$",
                      "status: processing", text, count=1, flags=re.MULTILINE)
        text = _append_frontmatter_field(
            text, "claimed_at", datetime.now().isoformat(timespec="seconds"))
        dest.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return dest


def complete_task(
    processing_path: Path,
    agent: AgentName,
    *,
    success: bool,
    result_summary: str,
    result_detail: str = "",
    error: Optional[str] = None,
) -> Path:
    bucket = "done" if success else "failed"
    dest = _agent_dir(agent, bucket) / processing_path.name
    try:
        text = processing_path.read_text(encoding="utf-8")
    except Exception:
        text = ""
    text = _append_frontmatter_field(text, "status", "done" if success else "failed")
    text = _append_frontmatter_field(
        text, "completed_at", datetime.now().isoformat(timespec="seconds"))
    result_block = (
        "\n\n---\n\n"
        f"## Result ({'OK' if success else 'FAIL'})\n\n"
        f"**Summary:** {result_summary}\n\n"
    )
    if result_detail:
        result_block += f"### Details\n\n{result_detail}\n"
    if error:
        result_block += f"\n### Error\n```\n{error}\n```\n"
    text += result_block
    dest.write_text(text, encoding="utf-8")
    try:
        processing_path.unlink()
    except Exception:
        pass
    return dest


def read_task(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    title = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    desc = ""
    in_desc = False
    for line in body.splitlines():
        if line.strip() in ("## Description", "## Beskrivning"):
            in_desc = True
            continue
        if in_desc:
            if line.startswith("## "):
                break
            desc += line + "\n"
    return {
        "meta": meta,
        "title": title,
        "description": desc.strip(),
        "body": body,
        "path": str(path),
    }
