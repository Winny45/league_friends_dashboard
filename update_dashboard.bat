@echo off
REM Refreshes friend stats and rebuilds the dashboard.
REM Double-click this file any time, or let Windows Task Scheduler run it for you
REM (see the "Auto-update" section in README.md for setup steps).

cd /d "%~dp0"

echo Fetching latest data from Riot...
python fetch_data.py
if errorlevel 1 (
    echo.
    echo fetch_data.py failed - see the error above.
    echo A common cause is an expired API key: grab a fresh one from
    echo https://developer.riotgames.com and paste it into config.json.
    pause
    exit /b 1
)

echo Rebuilding dashboard.html...
python generate_dashboard.py
if errorlevel 1 (
    echo.
    echo generate_dashboard.py failed - see the error above.
    pause
    exit /b 1
)

echo Done. dashboard.html is up to date.
