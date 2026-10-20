@echo off
REM Self-updater for the CV screening engine. Safe to run any time.
REM Works from the installed engine folder AND from the downloaded zip folder.
REM The WorkBuddy expert also runs this quietly before the first screen.
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\update_engine.py %*
  goto :done
)

REM No private environment in this folder, so this is the downloaded zip.
REM Update the installed engine instead. setup.bat installs it to C:\ when
REM that is writable, otherwise to the user's own folder.
set TARGET=C:\agent-cv-screening
if not exist "%TARGET%\venv\Scripts\python.exe" set TARGET=%USERPROFILE%\agent-cv-screening
if exist "%TARGET%\venv\Scripts\python.exe" (
  "%TARGET%\venv\Scripts\python.exe" "%TARGET%\scripts\update_engine.py" %*
  goto :done
)

echo The screening engine is not installed on this computer yet.
echo Run setup.bat first - it needs no other software and takes a few minutes.
pause
exit /b 1

:done
