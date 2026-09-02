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
    # The deploy is run under a hard timeout, because it has already hung once
    # in a way nothing could see. The CLI decided its saved login needed
    # refreshing, printed a device code, and sat on "Waiting for
    # authentication..." forever. Under the scheduled task there is no console
    # showing that, so the hour's run simply never ended. Neither --yes nor
    # CI=1 prevents it: --yes only answers confirmations, and this build asks
    # anyway.
    #
    # A token removes the question entirely. Put "vercel_token" in config.json
    # (which is gitignored) from vercel.com/account/tokens, and an unattended
    # run stops depending on a refreshable interactive session.
    $env:CI = "1"
    $token = $null
    if (Test-Path (Join-Path $PSScriptRoot "config.json")) {
        $token = (Get-Content (Join-Path $PSScriptRoot "config.json") -Raw |
                  ConvertFrom-Json).vercel_token
    }
    $deployArgs = @("deploy", "--prod", "--yes")
    if ($token) { $deployArgs += @("--token", $token) }

    # Built by hand rather than with Start-Process, which is the obvious way
    # and the wrong one: in Windows PowerShell its -PassThru object never
    # populates ExitCode, so it reads as $null. "$null -ne 0" is true, so a
    # deploy that had just finished in six seconds was reported as failed.
    # A Process started this way returns the real code.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "vercel.cmd"
    $psi.Arguments = ($deployArgs | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join " "
    $psi.WorkingDirectory = $static
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()
    # Read both pipes asynchronously. Reading one to the end before the other
    # deadlocks as soon as the CLI fills the pipe it is not being read from.
    $stdout = $proc.StandardOutput.ReadToEndAsync()
    $stderr = $proc.StandardError.ReadToEndAsync()

    $timedOut = -not $proc.WaitForExit(420000)   # seven minutes
    if ($timedOut) {
        # /T because the CLI is a .cmd wrapping node: killing the wrapper on
        # its own leaves node running and still waiting.
        & taskkill /PID $proc.Id /T /F | Out-Null
    }
    foreach ($task in @($stdout, $stderr)) {
        try { $task.Result -split "`n" | Where-Object { $_.Trim() -ne "" } } catch {}
    }

    if ($timedOut) {
        Write-Host "The deploy did not finish within seven minutes and was killed." -ForegroundColor Red
        Write-Host "If the output above asks you to visit a vercel.com/oauth/device link," -ForegroundColor Red
        Write-Host "the CLI wants an interactive login that a scheduled run cannot give it." -ForegroundColor Red
        Write-Host "Add a token from vercel.com/account/tokens to config.json as" -ForegroundColor Red
        Write-Host "'vercel_token' and this stops happening." -ForegroundColor Red
        exit 1
    }
    if ($proc.ExitCode -ne 0) {
        Write-Host "The deploy failed (exit $($proc.ExitCode)). The rebuilt page is in" -ForegroundColor Red
        Write-Host "$static and can be published by hand with:" -ForegroundColor Red
        Write-Host "  vercel.cmd deploy --prod --yes" -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Published." -ForegroundColor Green
