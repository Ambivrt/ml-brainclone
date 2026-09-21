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
import sys
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional


def _vault_root() -> Path:
    root = os.environ.get("VAULT_ROOT")
    if root:
        return Path(root)
    return Path.home() / "vault"


AgentName = Literal["larry", "harry", "barry", "parry", "tarry"]
VALID_AGENTS = ("larry", "harry", "barry", "parry", "tarry")

# Validity window: a task older than this that was never claimed should
# never run. This is what stops a stale one-off task (e.g. a scheduled
# action tied to yesterday) from firing a day late just because nothing
# happened to check on it in time.
DEFAULT_TASK_TTL_HOURS = 48.0


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
    ttl_hours: float = DEFAULT_TASK_TTL_HOURS,
) -> Path:
    """Create a new pending task file in 00-inbox/.

    `ttl_hours` sets `expires_at`: a task that never gets claimed within the
    window never runs (see `is_task_expired`/`sweep_expired_pending`).
    """
    if agent not in VALID_AGENTS:
        raise ValueError(f"Invalid agent: {agent}. Choose one of {VALID_AGENTS}")

    task_id = uuid.uuid4().hex[:8]
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(title)
    fname = f"task-{agent}-{ts}-{slug}-{task_id}.md"
    inbox = _inbox()
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / fname
    expires_at = (now + timedelta(hours=ttl_hours)).isoformat(timespec="seconds")

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
        f"created: {now.isoformat(timespec='seconds')}\n"
        f"expires_at: {expires_at}\n"
        f"privacy: 2\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"## Description\n{description}\n"
        f"{ctx_block}"
    )
    path.write_text(content, encoding="utf-8")
    return path


def _candidate_task_files(agent: AgentName) -> list[Path]:
    """Pending task files for an agent: `00-inbox/` (before a router has
    moved them) and `_tasks/<agent>/` (its root only, never `processing/`,
    `done/` or `failed/`, which have their own lifecycle)."""
    out: list[Path] = []
    inbox = _inbox()
    if inbox.exists():
        for p in inbox.glob("task-*.md"):
            if f"task-{agent}-" in p.name:
                out.append(p)
    agent_root = _tasks_root() / agent
    if agent_root.exists():
        out.extend(p for p in agent_root.glob("task-*.md") if p.is_file())
    return out


def _parse_dt(raw) -> Optional[datetime]:
    """Parse an ISO timestamp into a naive, local datetime. None if `raw`
    is missing or unparsable -- callers should then never assume the time
    has passed (better one extra pending task than one run on a guess)."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def is_task_expired(meta: dict, *, now: Optional[datetime] = None,
                     default_hours: float = DEFAULT_TASK_TTL_HOURS) -> bool:
    """True if the task has passed its validity window and must never run.

    `expires_at` (set by `create_task`) is authoritative when present. Older
    files without the field fall back to `created` + `default_hours`."""
    now = now or datetime.now()
    expires = _parse_dt(meta.get("expires_at"))
    if expires is not None:
        return expires <= now
    created = _parse_dt(meta.get("created"))
    if created is None:
        return False
    return created + timedelta(hours=default_hours) <= now


def list_pending_for_agent(agent: AgentName) -> list[Path]:
    """Pending task files for an agent, in `00-inbox/` or `_tasks/<agent>/`.

    Expired tasks are never returned here -- call `sweep_expired_pending(agent)`
    first (the watcher does this every loop) so a task past its window is
    never claimed, only moved to failed/."""
    out: list[Path] = []
    for p in _candidate_task_files(agent):
        try:
            meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("agent") == agent and meta.get("status", "pending") == "pending":
            out.append(p)
    out.sort(key=lambda p: p.stat().st_mtime)
    return out


def sweep_expired_pending(agent: AgentName, *, default_hours: float = DEFAULT_TASK_TTL_HOURS,
                          now: Optional[datetime] = None) -> list[Path]:
    """Move `pending` tasks whose validity window has passed to failed/ with
    status `expired`. Called by the watcher every loop, before it lists
    pending tasks -- an expired task should never get claimed."""
    now = now or datetime.now()
    moved: list[Path] = []
    for p in _candidate_task_files(agent):
        try:
            text = p.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(text)
        except Exception:
            continue
        if meta.get("agent") != agent:
            continue
        if meta.get("status", "pending") != "pending":
            continue
        if not is_task_expired(meta, now=now, default_hours=default_hours):
            continue

        dest = _agent_dir(agent, "failed") / p.name
        text = _append_frontmatter_field(text, "status", "expired")
        text = _append_frontmatter_field(text, "expired_at", now.isoformat(timespec="seconds"))
        text += (
            "\n\n---\n\n## Expired\n\n"
            f"The validity window ({default_hours:.0f}h) ran out before the task was "
            "claimed. It will never run late.\n"
        )
        try:
            dest.write_text(text, encoding="utf-8")
            p.unlink()
        except Exception:
            continue
        moved.append(dest)
    return moved


def triage_stale(*, default_hours: float = DEFAULT_TASK_TTL_HOURS, dry_run: bool = True,
                 now: Optional[datetime] = None) -> list[dict]:
    """One-off helper: find every `pending` task, for every agent, that is
    older than its validity window.

    `dry_run=True` (default) changes nothing, only reports. `dry_run=False`
    runs `sweep_expired_pending` per agent and the report gets `status_after`."""
    now = now or datetime.now()
    report: list[dict] = []
    for agent in VALID_AGENTS:
        for p in _candidate_task_files(agent):
            try:
                meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("agent") != agent:
                continue
            if meta.get("status", "pending") != "pending":
                continue
            if not is_task_expired(meta, now=now, default_hours=default_hours):
                continue
            report.append({
                "agent": agent,
                "path": str(p),
                "task_id": meta.get("task_id", p.stem),
                "created": meta.get("created", ""),
                "status_before": meta.get("status", "pending"),
            })

    if not dry_run:
        moved_names: set[str] = set()
        for agent in VALID_AGENTS:
            moved_names.update(d.name for d in
                               sweep_expired_pending(agent, default_hours=default_hours, now=now))
        for row in report:
            row["status_after"] = "expired" if Path(row["path"]).name in moved_names else "unchanged"

    return report


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


# ---------------------------------------------------------------------------
# CLI: python task_lib.py triage-stale [--apply] [--hours N]
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="task_lib.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("triage-stale", help="mark expired pending tasks as expired")
    t.add_argument("--apply", action="store_true", help="move them to failed/ (default: report only)")
    t.add_argument("--hours", type=float, default=DEFAULT_TASK_TTL_HOURS)

    ns = ap.parse_args(argv)

    if ns.cmd == "triage-stale":
        report = triage_stale(default_hours=ns.hours, dry_run=not ns.apply)
        for row in report:
            print(json.dumps(row, ensure_ascii=False))
        verb = "Moved" if ns.apply else "Would move (dry-run, pass --apply to act)"
        print(f"\n{verb}: {len(report)}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
