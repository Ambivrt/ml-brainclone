# stack-boot.ps1 -- full stack start after logon. Run by the "Stack Autostart" logon
# task that register-stack-task.ps1 creates.
#
# The whole stack should come up every time the computer restarts, except the
# parts the owner switched off in the control room (data/web/parts-off.json). That
# is a plain full stack-start.ps1: it skips the parts that are off and starts the
# rest. Already up means nothing happens.
#
# The "Stack Web - Always Up" task runs stack-start.ps1 -Only Web at the same logon.
# Two starts at once give two web apps on the same port (SO_REUSEADDR lets both
# bind), so this script first waits until the web task has finished, at most
# $WAIT_MAX_S. The access gate can take a minute or more on a network that has
# just woken up.
#
# Needs VAULT_ROOT as a user environment variable (a logon task inherits it).
# Log: <vault>\.notifications\autostart.log

$ErrorActionPreference = "Continue"
$VaultPath = $env:VAULT_ROOT
if (-not $VaultPath) { Write-Error "VAULT_ROOT not set"; exit 1 }
$Start   = Join-Path $PSScriptRoot "stack-start.ps1"
$LogDir  = Join-Path $VaultPath ".notifications"
$LogFile = Join-Path $LogDir "autostart.log"
$WebTask = "Stack Web - Always Up"
$WAIT_MAX_S = 180

if (-not (Test-Path $LogDir)) { New-Item -Path $LogDir -ItemType Directory -Force | Out-Null }
"" *>> $LogFile
"=== STACK BOOT $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" *>> $LogFile

$waited = 0
while ($waited -lt $WAIT_MAX_S) {
    $t = Get-ScheduledTask -TaskName $WebTask -ErrorAction SilentlyContinue
    if (-not $t -or $t.State -ne "Running") { break }
    Start-Sleep -Seconds 3
    $waited += 3
}
if ($waited -gt 0) { "  Waited $waited s for $WebTask" *>> $LogFile }

& $Start *>> $LogFile
exit $LASTEXITCODE
