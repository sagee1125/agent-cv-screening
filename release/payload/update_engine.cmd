@echo off
REM Self-updater for the CV screening engine. Safe to run any time.
REM Works from the installed engine folder AND from the downloaded zip folder.
REM The WorkBuddy expert also runs this quietly before the first screen.
cd /d "%~dp0"

set QUIET=
if "%~1"=="--quiet" set QUIET=1

if exist "venv\Scripts\python.exe" if exist "scripts\update_engine.py" (
  "venv\Scripts\python.exe" scripts\update_engine.py %*
  goto :done
)

REM No private environment in this folder, so this is the downloaded zip.
REM Update the installed engine instead - but only a CURRENT-shape install
REM (private venv AND the updater script inside it). An old-architecture copy
REM (everything in the root, no scripts\ folder) cannot be updated by it; a
REM blind run there printed "can't open file" and still reported success.
set TARGET=C:\agent-cv-screening
if exist "%TARGET%\venv\Scripts\python.exe" if exist "%TARGET%\scripts\update_engine.py" goto :have_installed
set TARGET=%USERPROFILE%\agent-cv-screening
if exist "%TARGET%\venv\Scripts\python.exe" if exist "%TARGET%\scripts\update_engine.py" goto :have_installed

REM Neither this folder nor an installed engine could be found.
echo The screening engine is not installed on this computer yet.
echo Run setup.bat first - it needs no other software and takes a few minutes.
if not defined QUIET pause
exit /b 1

:have_installed
"%TARGET%\venv\Scripts\python.exe" "%TARGET%\scripts\update_engine.py" %*

:done
REM The WorkBuddy expert calls this with --quiet from a hidden console; a pause
REM there would block the conversation. Manual double-click runs, however, must
REM not see the update result vanish instantly.
if defined QUIET exit /b %errorlevel%
echo.
pause
exit /b %errorlevel%
