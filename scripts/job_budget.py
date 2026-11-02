"""job_budget.py -- per-job measurement for headless runs: runs, turns and cost per day.

Borrowed from GitHub Agentic Workflows (gh-aw, GA 2026-10-28), where every
run logs tokens, AI credits and turns (`gh aw logs`, `gh aw forecast`). Only
the measurement lives here. A turn cap and a daily cap were built and backed
out the same day after an adversarial review: thresholds without data, and
loop_guard already stops loops. If the measurement shows a job running away,
that is the basis for a cap.

  written    the headless runner's output parser calls
             record(job, result_json) with the CLI's JSON result
             (num_turns, total_cost_usd, duration_ms)
  jobs       task watcher, brain worker, anything that runs `claude -p`
  read       `python scripts/job_budget.py report [--days N]`

total_cost_usd is the CLI's computed API price. On a subscription it is a
measure of consumption, not an invoice. The ledger is written under a file
lock, several daemons can write at the same time.

Ledger: job-budget-YYYY-MM-DD.json under LARRY_JOB_BUDGET_DIR, else
$LARRY_STATE_DIR/job-budget, else $VAULT_PATH/data/job-budget. With
LARRY_TEST_MODE=1 and no explicit dir it writes to the system temp dir, so
test suites never pollute the real ledger.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_DIR_ENV = "LARRY_JOB_BUDGET_DIR"
KEEP_DAYS = 30


def _state_dir() -> Path:
    env = os.environ.get(STATE_DIR_ENV)
    if env:
        return Path(env)
    # Test suites run jobs with mocks. Without this guard their runs would
    # land in the real ledger.
    if os.environ.get("LARRY_TEST_MODE") == "1":
        import tempfile
        return Path(tempfile.gettempdir()) / "larry-job-budget-test"
    base = os.environ.get("LARRY_STATE_DIR")
    if base:
        return Path(base) / "job-budget"
    return Path(os.environ.get("VAULT_PATH", ".")) / "data" / "job-budget"


def _ledger(day: date) -> Path:
    return _state_dir() / f"job-budget-{day.isoformat()}.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class _FileLock:
    """Minimal cross-process lock: an exclusively created sidecar file."""

    STALE_SECONDS = 30

    def __init__(self, target: Path, timeout_s: float = 10):
        self.path = target.with_name(target.name + ".lock")
        self.timeout_s = timeout_s
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.time() + self.timeout_s
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.STALE_SECONDS:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"lock timeout: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
        self.path.unlink(missing_ok=True)


def _prune(today: date) -> None:
    cutoff = today - timedelta(days=KEEP_DAYS)
    for p in _state_dir().glob("job-budget-*.json"):
        try:
            if date.fromisoformat(p.stem.removeprefix("job-budget-")) < cutoff:
                p.unlink()
        except (ValueError, OSError):
            pass


def usage(job: str, day: date | None = None) -> dict:
    j = (_read(_ledger(day or date.today())).get("jobs") or {}).get(job) or {}
    return {"runs": int(j.get("runs", 0)), "turns": int(j.get("turns", 0)),
            "cost_usd": float(j.get("cost_usd", 0.0)), "max_turns_in_run": int(j.get("max_turns_in_run", 0))}


def record(job: str, data: dict | None, today: date | None = None) -> None:
    """Write one run to today's ledger. A failure here never stops a job."""
    try:
        today = today or date.today()
        data = data if isinstance(data, dict) else {}
        path = _ledger(today)
        path.parent.mkdir(parents=True, exist_ok=True)
        turns = int(data.get("num_turns") or 0)
        with _FileLock(path, timeout_s=10):
            led = _read(path)
            j = led.setdefault("jobs", {}).setdefault(job, {})
            j["runs"] = int(j.get("runs", 0)) + 1
            j["turns"] = int(j.get("turns", 0)) + turns
            j["cost_usd"] = round(float(j.get("cost_usd", 0.0)) + float(data.get("total_cost_usd") or 0.0), 4)
            j["duration_s"] = round(float(j.get("duration_s", 0.0)) + float(data.get("duration_ms") or 0) / 1000, 1)
            j["max_turns_in_run"] = max(int(j.get("max_turns_in_run", 0)), turns)
            j["last"] = datetime.now().isoformat(timespec="seconds")
            _write(path, led)
        _prune(today)
    except Exception as e:  # noqa: BLE001
        print(f"job_budget: record failed ({e})", file=sys.stderr)


def report(days: int = 7) -> str:
    today = date.today()
    tot: dict[str, dict] = {}
    for i in range(days):
        for job, j in (_read(_ledger(today - timedelta(days=i))).get("jobs") or {}).items():
            t = tot.setdefault(job, {"runs": 0, "turns": 0, "cost_usd": 0.0, "peak_runs": 0,
                                     "peak_turns": 0, "max_in_run": 0})
            r, tu = int(j.get("runs", 0)), int(j.get("turns", 0))
            t["runs"] += r
            t["turns"] += tu
            t["cost_usd"] += float(j.get("cost_usd", 0.0))
            t["peak_runs"] = max(t["peak_runs"], r)
            t["peak_turns"] = max(t["peak_turns"], tu)
            t["max_in_run"] = max(t["max_in_run"], int(j.get("max_turns_in_run", 0)))
    lines = [f"Headless jobs, last {days} days"]
    if not tot:
        lines.append("No runs in the ledger.")
    for job, t in sorted(tot.items()):
        lines.append(
            f"- {job}: {t['runs']} runs, {t['turns']} turns, ${t['cost_usd']:.2f}. "
            f"Peak day {t['peak_runs']} runs / {t['peak_turns']} turns. "
            f"Most turns in one run {t['max_in_run']}")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["report"]:
        n = int(args[args.index("--days") + 1]) if "--days" in args else 7
        print(report(n))
    else:
        print("usage: python job_budget.py report [--days N]")
