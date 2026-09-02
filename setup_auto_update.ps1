# Registers a Windows scheduled task that runs update_and_publish.ps1 on a
# repeating interval, so the published site refreshes itself.
#
# Usage: right-click this file -> "Run with PowerShell"
# (or open PowerShell in this folder and run: .\setup_auto_update.ps1)
#
# If Windows blocks the script from running, open PowerShell as your normal
# user and run this once first:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

$folder = $PSScriptRoot
$script = Join-Path $folder "update_and_publish.ps1"
$taskName = "LeagueFriendsDashboard-AutoUpdate"

if (-not (Test-Path $script)) {
    Write-Host "Could not find update_and_publish.ps1 in $folder" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "How often should the site refresh?" -ForegroundColor Cyan
Write-Host "  1) Every 30 minutes"
Write-Host "  2) Every hour  (recommended)"
Write-Host "  3) Every 3 hours"
Write-Host "  4) Once a day at 09:00"
$choice = Read-Host "Choose [default: 2]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "2" }

# schtasks.exe rather than Register-ScheduledTask. The cmdlet needs an explicit
# repetition duration and rejects the usual "forever" value as out of range,
# where /SC MINUTE and /SC HOURLY repeat indefinitely by definition.
# /ST anchors the repetition, so setting it to a whole hour lands every run on
# the hour rather than on whatever minute the task happened to be created.
switch ($choice) {
    "1"     { $sched = @("/SC", "MINUTE", "/MO", "30", "/ST", "00:00"); $label = "every 30 minutes, on the hour and the half hour" }
    "3"     { $sched = @("/SC", "HOURLY", "/MO", "3", "/ST", "00:00");  $label = "every 3 hours, on the hour" }
    "4"     { $sched = @("/SC", "DAILY", "/ST", "09:00");               $label = "once a day at 09:00" }
    default { $sched = @("/SC", "HOURLY", "/MO", "1", "/ST", "00:00");  $label = "every hour, on the hour" }
}

# Started through run_hidden.vbs rather than powershell.exe directly. A task
# that launches PowerShell draws a console on the logged-in desktop every time
# it fires, and -WindowStyle Hidden does not help: the console exists before
# PowerShell reads its arguments, so it still flashes up. WScript with a window
# style of 0 never creates one. The output goes to auto_update.log instead.
$launcher = Join-Path $folder "run_hidden.vbs"
if (-not (Test-Path $launcher)) {
    Write-Host "Could not find run_hidden.vbs in $folder" -ForegroundColor Red
    exit 1
}

# The inner quotes have to survive schtasks parsing the whole thing as one
# command line, which is why the path is wrapped in escaped quotes.
$run = "wscript.exe \`"$launcher\`""

schtasks /Create /TN $taskName /TR $run @sched /F | Out-Null

# schtasks has no switch for either of these. A laptop that sleeps through
# an hour skips that run entirely and waits for the next one, and by default
# Windows will not start the task at all on battery.
try {
    $settings = (Get-ScheduledTask -TaskName $taskName).Settings
    $settings.StartWhenAvailable = $true           # run a missed slot on wake
    $settings.DisallowStartIfOnBatteries = $false
    $settings.StopIfGoingOnBatteries = $false
    Set-ScheduledTask -TaskName $taskName -Settings $settings | Out-Null
} catch {
    Write-Host "Could not set the catch-up options: $_" -ForegroundColor Yellow
}

# Registering can fail while still printing something reassuring, so the task
# is read back rather than assumed. This script used to claim success after a
# failed registration.
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host ""
    Write-Host "The task was not created. Nothing is scheduled." -ForegroundColor Red
    Write-Host "Run this to see why:" -ForegroundColor Red
    Write-Host "  schtasks /Create /TN '$taskName' /TR '$run' $($sched -join ' ') /F"
    exit 1
}

Write-Host ""
Write-Host "Done. '$taskName' will run $label." -ForegroundColor Green
Write-Host "Verified: the task exists and is $($task.State)."
Write-Host "Each run fetches, rebuilds and publishes, so the live site moves on its own."
Write-Host "It runs with no window. Read $(Join-Path $folder 'auto_update.log') to see how a run went."
Write-Host ""
Write-Host "One thing will stop it: a free Riot development key expires 24 hours" -ForegroundColor Yellow
Write-Host "after it is issued, so an unattended schedule fails every day until the" -ForegroundColor Yellow
Write-Host "key in config.json is replaced by hand. Apply for a Personal API Key at" -ForegroundColor Yellow
Write-Host "developer.riotgames.com if you want this to keep running without you." -ForegroundColor Yellow
Write-Host ""
Write-Host "A failed run changes nothing: data.json is only written when every"
Write-Host "friend came back, so the published site keeps its last good build."
Write-Host ""
Write-Host "To check on it:   Get-ScheduledTaskInfo -TaskName '$taskName'"
Write-Host "To run it now:    Start-ScheduledTask -TaskName '$taskName'"
Write-Host "To remove it:     Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
