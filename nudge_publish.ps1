# Asks GitHub to run the publish workflow now.
#
# GitHub's cron is a queue, not a clock. On this repo an hourly schedule
# delivered three runs in eight hours, and a fifteen-minute one delivered
# none in an hour, with the workflow active and the cron correct on the
# default branch. The scheduler is simply not dependable.
#
# This does not do the work. It asks GitHub to, so the fetch, the rebuild and
# the deploy still happen on GitHub's runner against the state repo. That
# matters: the machine running this never writes rank_history.json, so it
# cannot drift from the copy the workflow keeps. The old scheduled task did do
# the work, which is why running both would have split the rank history in two.
#
# The workflow's own gate still applies, so a nudge while the published page
# is under fifty-five minutes old costs about twenty seconds and changes
# nothing.
#
# Run it by hand, or every hour. Note it goes through run_hidden.vbs: a task
# that starts powershell.exe directly draws a console on the logged-in desktop
# every time it fires, which on an hourly schedule is an hourly window.
#   schtasks /Create /TN "LeagueDashboard-Nudge" /TR `
#     "wscript.exe `"$PWD\run_hidden.vbs`" nudge_publish.ps1" `
#     /SC HOURLY /MO 1 /ST 00:00 /F
#
# To stop:  schtasks /Delete /TN "LeagueDashboard-Nudge" /F

$ErrorActionPreference = "Stop"

$repo = "Winny45/league_friends_dashboard"
$workflow = "publish.yml"

# gh is already signed in on this machine, so there is no token to store here
# and nothing secret in this file.
$gh = Get-Command gh.exe -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "The GitHub CLI is not on PATH. Install it, or run 'gh auth login'." -ForegroundColor Red
    exit 1
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
& $gh.Source workflow run $workflow --repo $repo
if ($LASTEXITCODE -ne 0) {
    Write-Host "[$stamp] Could not ask GitHub to run it. Is 'gh auth status' still good?" -ForegroundColor Red
    exit 1
}
Write-Host "[$stamp] Asked GitHub to publish. It will skip if the live page is under 55 minutes old." -ForegroundColor Green
