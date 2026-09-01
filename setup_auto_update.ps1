# Registers a Windows Task Scheduler task that runs update_and_publish.ps1 on
# a repeating interval, so the published site refreshes itself.
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
Write-Host "  4) Once a day"
$choice = Read-Host "Choose [default: 2]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "2" }

# A run costs one account lookup, one league lookup and one match-id listing
# per queue per friend, plus a match detail for anything new. At seven friends
# that is well inside a development key's 100 requests per two minutes, so
# even the half-hourly option has room to spare.
switch ($choice) {
    "1" { $every = New-TimeSpan -Minutes 30; $label = "every 30 minutes" }
    "3" { $every = New-TimeSpan -Hours 3;    $label = "every 3 hours" }
    "4" { $every = $null;                    $label = "once a day at 09:00" }
    default { $every = New-TimeSpan -Hours 1; $label = "every hour" }
}

if ($null -eq $every) {
    $trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::ParseExact("09:00", "HH:mm", $null))
} else {
    # A daily trigger with a repetition is the combination Task Scheduler
    # accepts for "keep doing this forever".
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval $every -RepetitionDuration ([TimeSpan]::MaxValue)
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $folder

# StartWhenAvailable catches up a run the machine slept through; the time
# limit stops a hung fetch from blocking the next one.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Fetches from Riot, rebuilds the dashboard and publishes it." | Out-Null

Write-Host ""
Write-Host "Done. '$taskName' will run $label." -ForegroundColor Green
Write-Host "Each run fetches, rebuilds and publishes, so the live site moves on its own."
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
