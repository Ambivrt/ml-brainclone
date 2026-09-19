"""Tests for scripts/brief_output.py -- the shared write helper the morning
brief uses after the untrusted-input hardening (see
docs/security-untrusted-input.md). The session never writes the brief file
itself; it answers with stdout text that gets validated and written here."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import brief_output as bo  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "brief_output.py"

VALID_BRIEF = """---
tags: [generated/nightly, type/morning-brief]
status: active
created: 2026-09-19
privacy: 2
---

# Morning brief -- 2026-09-19

## Today
- 10:00 Meeting with a colleague

## Worth knowing
- Something worth reading, summarized in one line

## From last night
- Vault hygiene ran clean

-- Larry
"""


# --- validate_brief_text -----------------------------------------------------

def test_validate_accepts_well_formed_brief():
    ok, reason = bo.validate_brief_text(VALID_BRIEF)
    assert ok is True
    assert reason == ""


def test_validate_rejects_none():
    ok, reason = bo.validate_brief_text(None)
    assert ok is False
    assert "no text" in reason


def test_validate_rejects_empty_string():
    ok, reason = bo.validate_brief_text("")
    assert ok is False
    assert "empty" in reason


def test_validate_rejects_whitespace_only():
    ok, reason = bo.validate_brief_text("   \n\n   \n")
    assert ok is False
    assert "empty" in reason


def test_validate_rejects_too_short_text():
    ok, reason = bo.validate_brief_text("---\ntags: []\n---\nshort\n")
    assert ok is False
    assert "short" in reason


def test_validate_rejects_missing_front_matter():
    body_only = "Morning brief with no front matter, just enough long text " * 5
    ok, reason = bo.validate_brief_text(body_only)
    assert ok is False
    assert "front matter" in reason


def test_validate_accepts_text_with_leading_bom_and_newlines():
    text = "﻿\n\n" + VALID_BRIEF
    ok, reason = bo.validate_brief_text(text)
    assert ok is True, reason


def test_validate_respects_custom_min_length():
    text = "---\ntags: []\n---\njust long enough text here\n"
    ok, _ = bo.validate_brief_text(text, min_length=10)
    assert ok is True


# --- write_brief_atomic -------------------------------------------------------

def test_write_creates_new_file(tmp_path):
    target = tmp_path / "morning-brief-2026-09-19.md"
    wrote, reason = bo.write_brief_atomic(target, VALID_BRIEF)
    assert wrote is True
    assert reason == ""
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("---\n")


def test_write_creates_parent_dirs(tmp_path):
    target = tmp_path / "nested" / "dir" / "morning-brief-2026-09-19.md"
    wrote, _ = bo.write_brief_atomic(target, VALID_BRIEF)
    assert wrote is True
    assert target.exists()


def test_write_is_atomic_no_tmp_file_left_behind(tmp_path):
    target = tmp_path / "morning-brief-2026-09-19.md"
    bo.write_brief_atomic(target, VALID_BRIEF)
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert leftovers == []


def test_write_rejects_empty_text_and_keeps_previous_file(tmp_path):
    target = tmp_path / "morning-brief-2026-09-19.md"
    target.write_text(VALID_BRIEF, encoding="utf-8")
    original = target.read_text(encoding="utf-8")

    wrote, reason = bo.write_brief_atomic(target, "")
    assert wrote is False
    assert "empty" in reason
    assert target.read_text(encoding="utf-8") == original


def test_write_rejects_text_without_front_matter_and_keeps_previous_file(tmp_path):
    target = tmp_path / "morning-brief-2026-09-19.md"
    target.write_text(VALID_BRIEF, encoding="utf-8")
    original = target.read_text(encoding="utf-8")

    garbage = ("Just some text with no front matter, long enough to pass the "
               "minimum length check but still missing the required shape. "
               "Repeated to get past the two hundred character minimum "
               "without ever having a valid front matter block at the start.")
    wrote, reason = bo.write_brief_atomic(target, garbage)
    assert wrote is False
    assert "front matter" in reason
    assert target.read_text(encoding="utf-8") == original


def test_write_rejects_none_and_creates_nothing(tmp_path):
    target = tmp_path / "does-not-exist" / "morning-brief-2026-09-19.md"
    wrote, reason = bo.write_brief_atomic(target, None)
    assert wrote is False
    assert not target.exists()
    assert not target.parent.exists()


def test_write_overwrites_previous_valid_brief_with_new_valid_one(tmp_path):
    target = tmp_path / "morning-brief-2026-09-19.md"
    target.write_text(VALID_BRIEF.replace("colleague", "old-value"), encoding="utf-8")

    wrote, _ = bo.write_brief_atomic(target, VALID_BRIEF)
    assert wrote is True
    assert "colleague" in target.read_text(encoding="utf-8")
    assert "old-value" not in target.read_text(encoding="utf-8")


# --- CLI mode (how nightly-runner.sh calls the module) ------------------------

def test_cli_writes_file_and_exits_zero(tmp_path):
    src = tmp_path / "stdout-capture.txt"
    src.write_text(VALID_BRIEF, encoding="utf-8")
    dst = tmp_path / "morning-brief-2026-09-19.md"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(src), str(dst)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert dst.exists()


def test_cli_leaves_previous_file_and_exits_nonzero_on_invalid_input(tmp_path):
    src = tmp_path / "stdout-capture.txt"
    src.write_text("", encoding="utf-8")
    dst = tmp_path / "morning-brief-2026-09-19.md"
    dst.write_text(VALID_BRIEF, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(src), str(dst)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1
    assert dst.read_text(encoding="utf-8") == VALID_BRIEF


def test_cli_wrong_arg_count_exits_two():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "only-one-arg"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 2
