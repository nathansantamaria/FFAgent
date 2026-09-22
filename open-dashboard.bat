@echo off
REM Serves the dashboard over http so it can fetch Sleeper live.
REM
REM Opening dashboard.html by double-clicking gives the page origin "null",
REM and browsers refuse to let a null origin call an API. Served over http it
REM gets a real origin and tier-1 live fetching works -- data as of the second
REM you load it, rather than whenever the scheduled Action last ran.
REM
REM Double-click this file. Close the black window when you are done.

cd /d "%~dp0"
start "" http://localhost:8765/dashboard.html
echo.
echo   Dashboard: http://localhost:8765/dashboard.html
echo   Close this window to stop the server.
echo.
python -m http.server 8765
