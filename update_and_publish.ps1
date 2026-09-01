# Fetch, rebuild and publish, in one go.
#
# This is the only thing that moves the numbers a shared link shows. The
# Refresh button in the browser calls Riot from the viewer's own machine with
# the viewer's own key and patches what it can into the page in front of them:
# ranks, the games it just pulled, the chart, the trend. It writes nothing
# back, because the site is a static file on a CDN with no server behind it.
# Season totals, champion tables, matchups and the rings are computed here.
#
# Run it by hand, or let Task Scheduler run it (setup_auto_update.ps1).
#
# The catch worth knowing before scheduling it: a free Riot development key
# dies 24 hours after it is issued, so an unattended schedule will fail every
# day until the key in config.json is replaced. A Personal API Key, which Riot
# grants on request, does not expire and is what makes this worth automating.

param(
    [switch]$SkipDeploy,          # fetch and rebuild only
    [switch]$RefetchDetails       # also re-pull matches missing lane data
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$stamp] Fetching from Riot..." -ForegroundColor Cyan

$fetchArgs = @("fetch_data.py")
if ($RefetchDetails) { $fetchArgs += "--refetch-details" }
python @fetchArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "fetch_data.py failed. data.json was left untouched, so the published" -ForegroundColor Red
    Write-Host "site still shows the last good build. Nothing else has run." -ForegroundColor Red
    exit 1
}

Write-Host "Rebuilding dashboard.html..." -ForegroundColor Cyan
python generate_dashboard.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "generate_dashboard.py failed. Nothing has been published." -ForegroundColor Red
    exit 1
}

$static = Join-Path (Split-Path $PSScriptRoot -Parent) "league_dashboard_static"
if (-not (Test-Path $static)) {
    Write-Host "No static folder at $static, so there is nothing to publish to." -ForegroundColor Yellow
    exit 0
}

Copy-Item dashboard.html (Join-Path $static "index.html") -Force
foreach ($asset in @("og.png", "icon-180.png")) {
    if (Test-Path $asset) { Copy-Item $asset $static -Force }
}
Write-Host "Copied into $static" -ForegroundColor Cyan

if ($SkipDeploy) {
    Write-Host "Skipping deploy as asked." -ForegroundColor Yellow
    exit 0
}

Write-Host "Publishing..." -ForegroundColor Cyan
Push-Location $static
try {
    vercel.cmd deploy --prod
    if ($LASTEXITCODE -ne 0) {
        Write-Host "The deploy failed. The rebuilt page is in $static and can be" -ForegroundColor Red
        Write-Host "published by hand with: vercel.cmd deploy --prod" -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Published." -ForegroundColor Green
