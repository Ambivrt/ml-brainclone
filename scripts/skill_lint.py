"""skill_lint.py -- finds skills that are never opened or call things that do not exist.

The rules come from Harness^2 (google-research/harness2, Apache 2.0), where
they reject a whole harness proposal at validation:

- A skill nothing points at is never opened. It is dead weight.
- A skill nobody used in 30 days is an archive candidate (Hermes Agent 0.22,
  skill_usage.py logs the use). The owner decides.
- A script a skill calls must exist, otherwise the skill runs something that
  is not there.
- Frontmatter without `description:` is dropped silently at load.

Two skill systems are linted:

- Claude Code skills: `<root>/<name>/SKILL.md` under `$VAULT_PATH/.claude/skills`
  plus any roots in LARRY_SKILL_ROOTS (separated by the OS path separator).
  Folders with `.claude-plugin` are mods, not skills
- The vault skill catalog: an index file (`INDEX.md` or `skills-index.md`) and
  the markdown files next to it, in LARRY_SKILLS_DIR, else `$VAULT_PATH/skills`.
  A file the index does not link to is never found, a link that does not
  resolve is broken

Script and module references in a skill (`python tool.py`, `python -m pkg.mod`)
are looked up in the skill's folder, next to this file, and under VAULT_PATH.

CLI:
    python scripts/skill_lint.py            # errors give exit 1
    python scripts/skill_lint.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Make `import skill_usage` work when run as a script from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Files in the skill directory that are not skills.
NOT_SKILLS = {"index", "skills-index", "skill-spec", "readme"}
INDEX_NAMES = ("INDEX.md", "skills-index.md")

_FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)
_SCRIPT_RE = re.compile(r"\bpython3?\s+(?:-[A-Za-z]\s+)*([\w./:\\-]+\.py)\b")
_MODULE_RE = re.compile(r"\bpython3?\s+(?:-[A-Za-z]\s+)*-m\s+([\w.]+)")
_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning
    path: str
    message: str


def vault_root() -> Path:
    return Path(os.environ.get("VAULT_PATH", "."))


def cc_skill_roots() -> tuple[Path, ...]:
    extra = [Path(p) for p in (os.environ.get("LARRY_SKILL_ROOTS") or "").split(os.pathsep) if p]
    return (vault_root() / ".claude" / "skills", *extra)


def vault_skills_dir() -> Path:
    env = os.environ.get("LARRY_SKILLS_DIR")
    return Path(env) if env else vault_root() / "skills"


def code_roots() -> tuple[Path, ...]:
    return (Path(__file__).resolve().parent, vault_root())


def _frontmatter(text: str) -> dict[str, str] | None:
    m = _FM_RE.match(text)
    if not m:
        return None
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip("'\"")
    return fm


def _script_exists(ref: str, skill_dir: Path, roots: tuple[Path, ...]) -> bool:
    p = Path(ref.replace("\\", "/"))
    if p.is_absolute() or re.match(r"^[A-Za-z]:", ref) or ref.startswith("/"):
        return p.exists()
    return any((base / p).exists() for base in (skill_dir, *roots))


def _module_exists(mod: str, roots: tuple[Path, ...]) -> bool:
    rel = Path(*mod.split("."))
    return any(
        (root / rel).with_suffix(".py").exists() or (root / rel / "__init__.py").exists()
        for root in roots
    )


def _looks_external(mod: str, roots: tuple[Path, ...]) -> bool:
    """Modules from installed packages (pytest, ...) are not linted: only a
    top-level name that exists in one of the code roots is ours."""
    top = mod.split(".")[0]
    return not any((r / top).is_dir() or (r / f"{top}.py").is_file() for r in roots)


def lint_cc_skills(roots=None, roots_for_code=None) -> list[Finding]:
    roots = cc_skill_roots() if roots is None else roots
    croots = code_roots() if roots_for_code is None else roots_for_code
    out: list[Finding] = []
    for root in roots:
        if not Path(root).is_dir():
            continue
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            if (d / ".claude-plugin").exists():
                continue
            skill = d / "SKILL.md"
            if not skill.is_file():
                out.append(Finding("warning", str(d), "folder without SKILL.md, never loaded"))
                continue
            text = skill.read_text(encoding="utf-8")
            fm = _frontmatter(text)
            if fm is None:
                out.append(Finding("error", str(skill), "no frontmatter, the skill is dropped at load"))
                continue
            if not fm.get("description"):
                out.append(Finding("error", str(skill), "`description:` missing, the skill is dropped at load"))
            if fm.get("name") and fm["name"] != d.name:
                out.append(Finding("error", str(skill), f"`name: {fm['name']}` does not match the folder `{d.name}`"))
            for ref in sorted(set(_SCRIPT_RE.findall(text))):
                if not _script_exists(ref, d, croots):
                    out.append(Finding("error", str(skill), f"calls `{ref}` which does not exist"))
            for mod in sorted(set(_MODULE_RE.findall(text))):
                if not _looks_external(mod, croots) and not _module_exists(mod, croots):
                    out.append(Finding("error", str(skill), f"calls `-m {mod}` which does not exist"))
    return out


def _resolve_link(target: str, vault: Path, by_stem: dict[str, list[Path]]) -> bool:
    target = target.strip()
    if "/" in target:
        p = vault / target
        return p.exists() or p.with_suffix(".md").exists()
    return target.lower() in by_stem


def lint_vault_index(skills_dir=None, vault=None) -> list[Finding]:
    skills_dir = vault_skills_dir() if skills_dir is None else Path(skills_dir)
    vault = vault_root() if vault is None else Path(vault)
    if not skills_dir.is_dir():
        return []  # no catalog on this install
    index = next((skills_dir / n for n in INDEX_NAMES if (skills_dir / n).is_file()), None)
    if index is None:
        return [Finding("error", str(skills_dir), "skill index (INDEX.md) missing")]
    text = index.read_text(encoding="utf-8")
    links = _LINK_RE.findall(text)

    by_stem: dict[str, list[Path]] = {}
    for p in vault.rglob("*.md"):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        by_stem.setdefault(p.stem.lower(), []).append(p)

    out: list[Finding] = []
    for link in links:
        if not _resolve_link(link, vault, by_stem):
            out.append(Finding("error", str(index), f"[[{link}]] does not resolve to any file"))

    linked = {Path(link.strip()).name.lower() for link in links}
    for f in sorted(skills_dir.glob("*.md")):
        if f.stem.lower() in NOT_SKILLS:
            continue
        if f.stem.lower() not in linked:
            out.append(Finding("warning", str(f), "the index does not link here, the skill is never found"))
    return out


UNUSED_DAYS = 30


def _skill_files(cc_roots, skills_dir) -> dict[str, Path]:
    """{skill name: file} for both skill systems. The same name in two
    places counts once."""
    found: dict[str, Path] = {}
    for root in cc_roots:
        if Path(root).is_dir():
            for d in sorted(p for p in Path(root).iterdir() if (p / "SKILL.md").is_file()):
                found.setdefault(d.name, d / "SKILL.md")
    if Path(skills_dir).is_dir():
        for f in sorted(Path(skills_dir).glob("*.md")):
            if f.stem.lower() not in NOT_SKILLS:
                found.setdefault(f.stem, f)
    return found


def lint_unused(cc_roots=None, skills_dir=None, *, usage=None, now=None,
                days: int = UNUSED_DAYS) -> list[Finding]:
    """Skills not used in `days` days (skill_usage.py).

    Silent until the log itself is `days` days old, otherwise every skill
    becomes a candidate the first night. A skill newer than the cutoff is not
    flagged. The owner decides, nothing is archived here (Hermes Agent 0.22
    does it by itself).
    """
    from datetime import datetime, timedelta
    import skill_usage
    cc_roots = cc_skill_roots() if cc_roots is None else cc_roots
    skills_dir = vault_skills_dir() if skills_dir is None else skills_dir
    first, last = usage if usage is not None else skill_usage.summary()
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    if first is None or first > cutoff:
        return []
    out: list[Finding] = []
    for name, path in _skill_files(cc_roots, skills_dir).items():
        seen = last.get(name)
        if seen and seen >= cutoff:
            continue
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) > cutoff:
                continue
        except OSError:
            continue
        when = f"last {seen:%Y-%m-%d}" if seen else "never since the log started"
        out.append(Finding("warning", str(path),
                           f"unused for {days} days ({when}), archive candidate, the owner decides"))
    return out


def lint_all() -> list[Finding]:
    return lint_cc_skills() + lint_vault_index() + lint_unused()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    findings = lint_all()
    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f.level:7} {f.path}: {f.message}")
        if not findings:
            print("Skill lint: no findings")
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
