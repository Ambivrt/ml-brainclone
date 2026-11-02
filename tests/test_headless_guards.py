"""Focused tests for the headless guard modules (see docs/headless-guards.md).

No network. All state goes to tmp_path through the *_DIR / *_LOG env vars.
Fake credentials are built at runtime so no key-shaped literal sits in the file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import credential_scan  # noqa: E402
import envelope  # noqa: E402
import extern_taint  # noqa: E402
import job_budget  # noqa: E402
import loop_guard  # noqa: E402
import protected_files  # noqa: E402
import skill_lint  # noqa: E402
import skill_usage  # noqa: E402


# -- loop_guard ---------------------------------------------------------------


@pytest.fixture
def lg(tmp_path, monkeypatch):
    monkeypatch.setenv(loop_guard.STATE_DIR_ENV, str(tmp_path / "lg"))
    return loop_guard


def test_loop_guard_blocks_after_same_response_repeats(lg):
    inp = {"pattern": "needle"}
    reasons = [lg.record("s1", "Grep", inp, "no matches") for _ in range(lg.SAME_RESULT_LIMIT)]
    assert reasons[:-1] == [None] * (lg.SAME_RESULT_LIMIT - 1)
    assert "same response" in reasons[-1]
    assert lg.check("s1", "Grep", inp)
    assert lg.check("s1", "Grep", {"pattern": "other"}) is None


def test_loop_guard_changing_response_is_not_a_loop(lg):
    inp = {"command": "git status"}
    for i in range(lg.TOTAL_LIMIT - 1):
        assert lg.record("s2", "Bash", inp, f"output {i}") is None
    assert lg.check("s2", "Bash", inp) is None


def test_loop_guard_new_edit_resets_and_exempt_tools_ignored(lg):
    inp = {"pattern": "x"}
    for _ in range(lg.SAME_RESULT_LIMIT):
        lg.record("s3", "Grep", inp, "same")
    assert lg.check("s3", "Grep", inp)
    lg.record("s3", "Edit", {"file_path": "a.txt", "new_string": "b"}, "ok")
    assert lg.check("s3", "Grep", inp) is None
    assert lg.record("s3", "Monitor", {}, "same") is None


def test_loop_guard_denials_counter(lg):
    assert lg.denials("s4") == 0
    lg.note_denied("s4", "reason")
    lg.note_denied("s4", "reason")
    assert lg.denials("s4") == 2


def test_loop_guard_hook_denies_headless_only(lg, tmp_path):
    env = {**os.environ, loop_guard.STATE_DIR_ENV: str(tmp_path / "lg")}
    hook = SCRIPTS / "hooks" / "loop-guard.py"
    inp = {"pattern": "needle"}
    for _ in range(loop_guard.SAME_RESULT_LIMIT):
        loop_guard.record("hs", "Grep", inp, "none")
    pre = json.dumps({"hook_event_name": "PreToolUse", "session_id": "hs",
                      "tool_name": "Grep", "tool_input": inp})
    headless = subprocess.run([sys.executable, str(hook)], input=pre, text=True, capture_output=True,
                              env={**env, "LARRY_HEADLESS": "1"})
    assert json.loads(headless.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    interactive = subprocess.run([sys.executable, str(hook)], input=pre, text=True, capture_output=True,
                                 env={k: v for k, v in env.items() if k != "LARRY_HEADLESS"})
    assert interactive.stdout == ""
    assert interactive.returncode == 0


# -- protected_files ----------------------------------------------------------


@pytest.mark.parametrize("path", [
    "/vault/CLAUDE.md",
    "/vault/sub/CLAUDE.md",
    "/vault/.claude/settings.json",
    "/vault/.claude/hooks/privacy-guard.py",
    "/vault/.claude/skills/x/SKILL.md",
    "/repo/.mcp.json",
    "/repo/.git/hooks/pre-commit",
    "/repo/scripts/loop_guard.py",
    "/cfg/config/secrets/keys.env",
])
def test_protected_paths(path):
    assert protected_files.is_protected(path)


@pytest.mark.parametrize("path", ["/vault/notes/today.md", "/repo/scripts/idempotency.py", "", "/vault/claude.md.bak"])
def test_unprotected_paths(path):
    assert not protected_files.is_protected(path)


def test_protected_relative_path_resolves_against_cwd():
    assert protected_files.tool_hit("Edit", {"file_path": "CLAUDE.md"}, cwd="/vault")
    assert protected_files.tool_hit("Bash", {"file_path": "CLAUDE.md"}, cwd="/vault") is None
    assert protected_files.tool_hit("Write", {"file_path": "notes.md"}, cwd="/vault") is None


def test_protected_applies_only_unattended_headless():
    assert protected_files.applies({"LARRY_HEADLESS": "1"})
    assert not protected_files.applies({"LARRY_HEADLESS": "1", "LARRY_OWNER_ORDER": "1"})
    assert not protected_files.applies({})


def test_protected_extra_patterns(monkeypatch):
    monkeypatch.setenv(protected_files.EXTRA_ENV, r"/private-notes/;(")
    assert protected_files.is_protected("/vault/private-notes/a.md")


# -- job_budget ---------------------------------------------------------------


def test_job_budget_records_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv(job_budget.STATE_DIR_ENV, str(tmp_path / "jb"))
    job_budget.record("watcher", {"num_turns": 7, "total_cost_usd": 0.5, "duration_ms": 2000})
    job_budget.record("watcher", {"num_turns": 3, "total_cost_usd": 0.25})
    job_budget.record("watcher", None)  # garbage never raises
    u = job_budget.usage("watcher")
    assert u["runs"] == 3 and u["turns"] == 10 and u["max_turns_in_run"] == 7
    assert u["cost_usd"] == pytest.approx(0.75)
    assert "watcher: 3 runs, 10 turns" in job_budget.report(1)


def test_job_budget_prunes_old_ledgers(tmp_path, monkeypatch):
    d = tmp_path / "jb"
    monkeypatch.setenv(job_budget.STATE_DIR_ENV, str(d))
    old = date.today() - timedelta(days=job_budget.KEEP_DAYS + 5)
    job_budget.record("j", {"num_turns": 1}, today=old)
    job_budget.record("j", {"num_turns": 1})
    assert not (d / f"job-budget-{old.isoformat()}.json").exists()
    assert (d / f"job-budget-{date.today().isoformat()}.json").exists()


def test_job_budget_test_mode_does_not_touch_vault(tmp_path, monkeypatch):
    monkeypatch.delenv(job_budget.STATE_DIR_ENV, raising=False)
    monkeypatch.setenv("LARRY_TEST_MODE", "1")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    assert str(tmp_path / "vault") not in str(job_budget._state_dir())


# -- extern_taint -------------------------------------------------------------


@pytest.fixture
def et(tmp_path, monkeypatch):
    monkeypatch.setenv(extern_taint.STATE_DIR_ENV, str(tmp_path / "et"))
    monkeypatch.delenv(extern_taint.MODE_ENV, raising=False)
    monkeypatch.delenv(extern_taint.HEADLESS_ENV, raising=False)
    return extern_taint


def test_tool_source_classification(et):
    assert et.tool_source("WebFetch", {"url": "https://example.org/a"}).startswith("WebFetch")
    assert et.tool_source("Bash", {"command": "curl -s https://example.org/x"}).startswith("curl")
    assert et.tool_source("Bash", {"command": "curl http://localhost:8080/health"}) is None
    assert et.tool_source("Bash", {"command": "gh issue view 4"}) == "github"
    assert et.tool_source("Bash", {"command": "ls -la"}) is None
    assert et.tool_source("mcp__claude-in-chrome__get_page_text", {}) == "get_page_text"
    assert et.tool_source("mcp__claude-in-chrome__navigate", {}) is None
    assert et.tool_source("Read", {"file_path": "a.md"}) is None


def test_taint_is_sticky_per_session(et):
    assert not et.tainted("a")
    et.record("a", "curl: https://example.org")
    assert et.tainted("a") and not et.tainted("b")
    assert et.load("a")["count"] == 1


def test_verdict_raises_only_headless_enforce(et, monkeypatch):
    et.record("a", "WebFetch: https://example.org")
    assert et.verdict("clean", "on_loop") is None
    assert et.verdict("a", "on_loop", internal=True) is None
    assert et.verdict("a", "in_loop") is None
    assert et.verdict("a", "in_loop", marker=True) is not None
    assert et.verdict("a", "autonomous")["raise"] is False  # interactive
    monkeypatch.setenv(et.HEADLESS_ENV, "1")
    assert et.verdict("a", "autonomous")["raise"] is True
    monkeypatch.setenv(et.MODE_ENV, "shadow")
    assert et.verdict("a", "autonomous")["raise"] is False


def test_extern_taint_hook_records(et, tmp_path):
    hook = SCRIPTS / "hooks" / "extern-taint-read.py"
    payload = json.dumps({"session_id": "hk", "tool_name": "WebSearch", "tool_input": {"query": "x"}})
    env = {**os.environ, extern_taint.STATE_DIR_ENV: str(tmp_path / "et")}
    r = subprocess.run([sys.executable, str(hook)], input=payload, text=True, capture_output=True, env=env)
    assert r.returncode == 0 and r.stdout == ""
    assert extern_taint.tainted("hk")


# -- credential_scan ----------------------------------------------------------


def _fake_keys() -> dict[str, str]:
    return {
        "github-pat": "ghp_" + "a1B2" * 9,
        "aws-access-key": "AKIA" + "IOSFODNN7EXAMPLE",
        "pem-private-key": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "anthropic-api-key": "sk-ant-" + "x" * 24,
    }


def test_scan_finds_generic_formats_and_never_returns_the_key():
    for rule, key in _fake_keys().items():
        hits = credential_scan.scan(f"config value: {key} end")
        assert rule in hits
        assert all(key not in h for h in hits)


def test_scan_ignores_placeholders_but_catches_env_assignment():
    assert credential_scan.scan("API_KEY=$env:MY_KEY") == []
    assert credential_scan.scan("TOKEN: <your token here>") == []
    assert credential_scan.scan("export SERVICE_TOKEN=abcdef123456") == ["env-secret-assignment"]


def test_redact_replaces_keys_and_keeps_env_names():
    keys = _fake_keys()
    text, hits = credential_scan.redact(f"a {keys['github-pat']} b\nDB_PASSWORD=hunter2hunter2")
    assert keys["github-pat"] not in text and "hunter2hunter2" not in text
    assert "DB_PASSWORD=[REDACTED:env-secret-assignment]" in text
    assert set(hits) == {"github-pat", "env-secret-assignment"}
    assert credential_scan.redact("") == ("", [])


# -- envelope -----------------------------------------------------------------


def test_envelope_owner_vs_agent():
    assert envelope.task_origin({"from_source": "telegram"}) == ("the owner via chat", True)
    assert envelope.task_origin({"from_source": "telegram", "generated-by": "scarry"}) == ("scarry", False)
    assert envelope.task_origin({}) == ("unknown sender", False)
    assert envelope.task_origin({"from_source": "scanner"}) == ("scanner", False)


def test_envelope_header_and_bus_marker():
    assert envelope.task_header({"from_source": "dashboard"}, "barry").startswith("This is a dispatched task")
    h = envelope.task_header({"generated-by": "tarry"}, "barry")
    assert "not from the owner" in h and "(dispatched to Barry)" in h
    assert envelope.bus_marker("owner") == ""
    assert envelope.bus_marker("tarry") == " [agent data, not an order]"


# -- skill_usage and skill_lint ----------------------------------------------


def test_skill_usage_detects_tool_and_read(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv(skill_usage.LOG_ENV, str(log))
    assert skill_usage.skill_from_payload({"tool_name": "Skill", "tool_input": {"skill": "/my-skill"}}) == "my-skill"
    read = lambda p: {"tool_name": "Read", "tool_input": {"file_path": p}}  # noqa: E731
    assert skill_usage.skill_from_payload(read("/v/.claude/skills/foo/SKILL.md")) == "foo"
    assert skill_usage.skill_from_payload(read("/v/skills/bar.md")) == "bar"
    assert skill_usage.skill_from_payload(read("/v/skills/INDEX.md")) is None
    assert skill_usage.skill_from_payload(read("/v/notes/bar.md")) is None
    assert skill_usage.record({"tool_name": "Skill", "tool_input": {"skill": "plug:rescue"}, "session_id": "s"},
                              now=datetime(2026, 1, 2, 3, 4, 5)) == "plug:rescue"
    first, last = skill_usage.summary()
    assert first == datetime(2026, 1, 2, 3, 4, 5)
    assert set(last) == {"plug:rescue", "rescue"}


def _mk_skill(root: Path, name: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def test_skill_lint_flags_missing_description_name_and_script(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    root = tmp_path / ".claude" / "skills"
    _mk_skill(root, "good", "---\nname: good\ndescription: does a thing\n---\nRun `python skill_lint.py`.\n")
    _mk_skill(root, "nodesc", "---\nname: nodesc\n---\nbody\n")
    _mk_skill(root, "wrongname", "---\nname: other\ndescription: x\n---\n")
    _mk_skill(root, "ghost", "---\nname: ghost\ndescription: x\n---\nRun `python missing_script.py`.\n")
    _mk_skill(root, "nofm", "just text\n")
    msgs = {Path(f.path).parent.name: f.message for f in skill_lint.lint_cc_skills() if f.level == "error"}
    assert "description" in msgs["nodesc"]
    assert "does not match" in msgs["wrongname"]
    assert "missing_script.py" in msgs["ghost"]
    assert "frontmatter" in msgs["nofm"]
    assert "good" not in msgs


def test_skill_lint_index_and_unused(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    sk = tmp_path / "skills"
    sk.mkdir()
    (sk / "INDEX.md").write_text("- [[alpha]]\n- [[nowhere]]\n", encoding="utf-8")
    (sk / "alpha.md").write_text("a", encoding="utf-8")
    (sk / "beta.md").write_text("b", encoding="utf-8")
    found = {(f.level, Path(f.path).name) for f in skill_lint.lint_vault_index()}
    assert ("error", "INDEX.md") in found      # [[nowhere]] broken
    assert ("warning", "beta.md") in found     # not linked from the index
    assert ("warning", "alpha.md") not in found

    old = datetime.now() - timedelta(days=90)
    os.utime(sk / "alpha.md", (old.timestamp(), old.timestamp()))
    os.utime(sk / "beta.md", (old.timestamp(), old.timestamp()))
    now = datetime.now()
    usage = (now - timedelta(days=60), {"alpha": now - timedelta(days=2)})
    unused = {Path(f.path).name for f in skill_lint.lint_unused(usage=usage)}
    assert unused == {"beta.md"}
    # log younger than the window: stay silent
    assert skill_lint.lint_unused(usage=(now - timedelta(days=3), {})) == []
