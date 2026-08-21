# Registers a Windows Task Scheduler task that runs update_dashboard.bat
# automatically every day, so the dashboard refreshes itself without you
# having to run anything by hand.
#
# Usage: right-click this file -> "Run with PowerShell"
# (or open PowerShell in this folder and run: .\setup_auto_update.ps1)
#
# If Windows blocks the script from running, open PowerShell as your normal
# user and run this once first:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

$folder = $PSScriptRoot
$batPath = Join-Path $folder "update_dashboard.bat"
$taskName = "LeagueFriendsDashboard-AutoUpdate"

if (-not (Test-Path $batPath)) {
    Write-Host "Could not find update_dashboard.bat in $folder" -ForegroundColor Red
    exit 1
}

$defaultTime = "09:00"
$timeInput = Read-Host "What time should it refresh each day? (24h format, e.g. 09:00) [default: $defaultTime]"
if ([string]::IsNullOrWhiteSpace($timeInput)) { $timeInput = $defaultTime }

try {
    $triggerTime = [DateTime]::ParseExact($timeInput, "HH:mm", $null)
} catch {
    Write-Host "Couldn't understand '$timeInput' as a time (expected HH:mm, e.g. 09:00). Aborting." -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $folder
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Refreshes the League Friends Dashboard (fetch_data.py + generate_dashboard.py) daily." | Out-Null

Write-Host ""
Write-Host "Done. '$taskName' is scheduled to run daily at $timeInput." -ForegroundColor Green
Write-Host "It runs even if dashboard.html is closed - just reopen the file (or refresh the browser tab) after it runs to see updates."
Write-Host ""
Write-Host "Reminder: a free Riot development API key expires every 24 hours, so a" -ForegroundColor Yellow
Write-Host "scheduled run will fail once it does. See the 'Auto-update' section in" -ForegroundColor Yellow
Write-Host "README.md for how to fix that (a Personal API Key never expires)." -ForegroundColor Yellow
Write-Host ""
Write-Host "To remove this scheduled task later, run:"
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
