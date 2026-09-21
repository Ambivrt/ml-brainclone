# Four-Way Code Layout: Source, Runtime, Binaries, Config

Source code, the deployed copy that daemons actually run from, binaries, and configuration live in four separate places on disk. A deploy script is the only thing that moves code from the first place to the second, and it never runs untested.

## The problem it solves

It's tempting to let daemons run directly out of a git working copy, especially early on: one less moving part, edits take effect immediately, no deploy step to remember. This works right up until you edit a file while a daemon is mid-read of it, or a daemon crashes on a half-finished change you were still working through, or you can no longer answer "what code is actually running right now" because the answer is "whatever the working tree looked like at some unrecorded point in time".

Separating "where I edit" from "where it runs" turns that question into something you can always answer exactly, and it makes a deploy a deliberate, auditable event instead of an implicit side effect of saving a file.

## The mechanism

Four directories, four jobs:

| Location | Contents |
|---|---|
| Source repo | The actual code, under version control. All editing happens here. |
| Runtime | A deployed copy plus whatever state daemons accumulate while running (heartbeats, logs, queues, PID files). Daemons only ever run from here. |
| Binaries | Compiled or downloaded executables that don't belong in either of the above. |
| Config | Configuration files, model weights, anything environment-specific that shouldn't be versioned alongside code or mixed into runtime state. |

A knowledge base or notes vault, if your system has one, is a fifth place, and it holds only text: specs, architecture notes, decisions. It never holds code, even small scripts. The temptation to drop a "quick script" into the notes vault because it's already open is exactly how a fifth, unversioned, untested copy of your logic appears.

The deploy script is the only bridge between the source repo and the runtime copy, and it does five things in a fixed order:

```powershell
# deploy.ps1 sketch
# 1. Refuse a dirty working tree unless explicitly overridden.
$dirty = git status --porcelain
if ($dirty -and -not $AllowDirty) {
    Write-Host "Working tree is dirty. Commit first, or override explicitly."
    exit 1
}

# 2. Run the test suite. Never deploy on red.
& python -m pytest . -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 3. Copy repo to runtime, without deleting runtime-only state (no purge).
& robocopy $Repo $Runtime /E /XD ".git" "__pycache__" /XF "*.pyc"

# 4. Record exactly what's running: commit hash and timestamp.
"$head`ndeployed: $(Get-Date)" | Out-File "$Runtime\DEPLOYED-COMMIT"

# 5. Verify the entrypoints actually landed where daemons expect them.
$missing = $Entrypoints | Where-Object { -not (Test-Path "$Runtime\$_") }
if ($missing) { Write-Host "Missing after deploy:"; $missing; exit 1 }

if ($Restart) { & "$Runtime\start-all.ps1" -Force }
```

A few details in that order matter more than they look:

**No purge on the copy step.** The runtime directory accumulates state (PID files, heartbeats, queues, logs) that has nothing to do with the source repo and must never be deleted by a routine deploy. A copy step that mirrors the source exactly, deleting anything in the destination not present in the source, will happily wipe out the queue a daemon was mid-processing.

**A deploy marker with the commit hash.** After every deploy, one file in the runtime directory states exactly which commit is running and when it was deployed. This turns "what's actually running" from a question you have to reconstruct into a value you can just read. A dirty deploy (uncommitted changes pushed through deliberately) gets flagged in that same marker rather than looking identical to a clean one.

**Verify entrypoints after copying, not before.** A robocopy or rsync that appears to succeed can still miss files due to exclusion patterns, permissions, or a path typo. Checking that the specific files daemons need to find are actually present after the copy catches a broken deploy immediately, rather than an hour later when a daemon fails to start and nobody's watching.

**Restart is a separate, explicit flag.** Copying new code and restarting the processes that run it are two different decisions with two different blast radii. A deploy that only copies files can be run freely; a deploy that also restarts every daemon should be a decision you make on purpose, especially when several daemons share a queue or an in-memory index that a restart would reset.

## How to adopt this in a fork

1. Pick four directories (or fewer, if binaries and config genuinely fit in one place for your setup) and put them somewhere consistent, referenced only through environment variables like `VAULT_PATH`, `RUNTIME_PATH`, `CONFIG_PATH`, never hardcoded absolute paths. This is also what lets the whole setup survive a machine reinstall or a change of account name without touching a single line of code.
2. Write the deploy script before you write your second daemon. Retrofitting a deploy step onto a system where three daemons already run straight from the working copy is a bigger job than starting with the separation.
3. Make the test suite a hard gate in the deploy script, not a step you run manually beforehand and hope you remember. If tests can't run in under a minute or two, that's worth fixing on its own; a deploy gate people routinely skip with a flag stops being a gate.
4. Add the entrypoint verification list as you go: every time you add a new daemon or a new hook the harness calls by exact path, add its path to the list the deploy script checks after copying.
5. Keep runtime-only state (heartbeats, PID files, queues) out of the source repo's `.gitignore`d directories if at all possible, so there's no ambiguity about which copy of a stateful file is the real one.

## Pitfalls

**Editing the runtime copy directly "just this once".** The runtime copy exists specifically so that "what's running" and "what you're actively editing" can never be the same file. An edit made directly in runtime gets silently overwritten by the next deploy, and now there are two versions of a fix and no record of which one is live.

**A deploy script that purges runtime.** This is the single most damaging mistake in this pattern. A destination-mirroring copy step will delete anything in runtime not present in source, which includes every queue, heartbeat, and log a daemon has ever written. Use a copy mode that adds and updates but does not delete, or exclude the state directories explicitly.

**Skipping tests under time pressure and forgetting to re-enable the gate.** A `--skip-tests` escape hatch is useful for genuine emergencies. It's also exactly the kind of flag that quietly becomes the default once someone uses it once under pressure. Make the skip visible and loud in the deploy output every time it's used.

**Binaries or config drifting into the source repo.** A large downloaded binary or a machine-specific config file committed into source control bloats the repo and creates a second source of truth for something that should live in the config or binaries directory. If it isn't code you wrote and version, it probably belongs in one of the other three places.

## See also

- [daemon-stability.md](daemon-stability.md) for the singleton, heartbeat, and watchdog patterns that assume daemons run from a stable runtime location
- [privacy-architecture.md](privacy-architecture.md) for keeping the source repo private while a public scaffold repo stays a skeleton
