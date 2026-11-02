# register-stack-task.ps1 -- start the stack at logon through Task Scheduler.
#
#   .\register-stack-task.ps1         "Stack Autostart": stack-boot.ps1, 45 s after
#                                     logon. A full stack start, minus the parts the
#                                     owner switched off in the control room. It
#                                     waits for the web task below to finish first.
#   .\register-stack-task.ps1 -Web    "Stack Web - Always Up": stack-start.ps1
#                                     -Only Web, 30 s after logon. Starts the web app
#                                     (with its tunnel port when the access policy
#                                     verifies) and the tunnel client, nothing else.
#
# Run both once per Windows installation: the web task keeps the web app reachable
# from a phone even if the full start is slow, the autostart brings up the rest.
# Already up means nothing happens. stack-stop leaves the web app and tunnel running
# on a normal stop, so a "stack off" lasts until the next reboot.
#
# Elevated: the web app may need admin rights to control the stack, and a full start
# can be the one that starts it. Run this script in an elevated terminal.
# conhost --headless: powershell.exe launched by Task Scheduler would otherwise flash
# a window at every logon.
# Idempotent: an existing task with the same name is removed and created again.
# VAULT_ROOT must be set as a user environment variable; the task inherits it.

param([switch]$Web)

$ErrorActionPreference = "Stop"

if ($Web) {
    $TaskName = "Stack Web - Always Up"
    $Delay    = "PT30S"
    $Script   = Join-Path $PSScriptRoot "stack-start.ps1"
    $LogFile  = Join-Path $env:VAULT_ROOT ".notifications\web-autostart.log"
    $PsArgs   = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"& '$Script' -Only Web *>> '$LogFile'`""
    $Desc     = "Starts the web app and the tunnel 30 s after logon. The rest of the stack is started by the autostart task."
} else {
    $TaskName = "Stack Autostart"
    $Delay    = "PT45S"
    $Script   = Join-Path $PSScriptRoot "stack-boot.ps1"
    $LogFile  = Join-Path $env:VAULT_ROOT ".notifications\autostart.log"
    $PsArgs   = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`""
    $Desc     = "Starts the whole stack 45 s after logon. Parts switched off in the control room are not started."
}

if (-not $env:VAULT_ROOT) {
    Write-Host "ERROR: VAULT_ROOT not set"
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Host "ERROR: $Script not found"
    exit 1
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "ERROR: run in an elevated terminal. The task starts the stack as admin."
    exit 1
}

$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless powershell.exe $PsArgs" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = $Delay

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed existing task $TaskName"
} catch {}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description $Desc | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "Registered: $($t.TaskName) [$($t.State)] -- $user, $($Delay -replace '^PT','' -replace 'S',' s') after logon"
Write-Host "Log:   $LogFile"
Write-Host "Test:  schtasks /Run /TN `"$TaskName`""
Write-Host "Remove: schtasks /Delete /TN `"$TaskName`" /F"
